import os
import pyshark
import csv

# --- MAPPING CONFIGURATION ---
# Maps Decimal or Hex IDs to Human Readable Names.
# Includes standard curves and common PQC/Hybrid codepoints.
GROUP_MAPPING = {
    # Standard Elliptic Curves
    23: 'secp256r1',
    24: 'secp384r1',
    25: 'secp521r1',
    29: 'x25519',
    30: 'x448',

    # Source: https://datatracker.ietf.org/doc/html/draft-ietf-tls-ecdhe-mlkem-02#section-7.3
    # Post-Quantum / Hybrid Codepoints (Subject to change as standards evolve)
    # These are common codepoints used by Chrome, Cloudflare, Google during experiments
    0x6399: 'x25519_kyber768 (Draft/Experiment)',
    0x639A: 'SecP256r1Kyber768Draft00',
    0x11ec: 'x25519_mlkem768',  # Used in recent Chrome versions
    0x4468: 'x25519_kyber768 (Old Draft)',
    0x11EB: 'SecP256r1MLKEM768',
    0x11ED: 'SecP384r1MLKEM1024'
}


def resolve_group_name(raw_value):
    """
    Tries to convert a raw group ID (string, int, or hex) into a human name.
    """
    if not raw_value:
        return "Unknown"

    try:
        # Check if it's hex string like "0x001d" or decimal string "29"
        if isinstance(raw_value, str) and raw_value.startswith('0x'):
            val_int = int(raw_value, 16)
        else:
            val_int = int(raw_value)

        return GROUP_MAPPING.get(val_int, str(val_int))
    except ValueError:
        return raw_value


def analyze_pcap_files(root_folder, output_csv):
    """
    Recursively scans for 'raw' pcaps, extracting TLS 1.3 Key Shares.
    Deduplicates based on (SNI, Algorithm).
    """

    headers = [
        'File Name',
        'Packet Number',
        'Server Name (SNI)',
        'Key Exchange Group (Algo)',
        'Source IP',
        'Destination IP'
    ]

    # 1. Gather all files first to calculate 'max'
    files_to_scan = []
    print(f"Scanning directory '{root_folder}' for files...")

    for dirpath, _, filenames in os.walk(root_folder):
        for filename in filenames:
            if 'raw' in filename and (filename.endswith('.pcap') or filename.endswith('.pcapng')):
                files_to_scan.append(os.path.join(dirpath, filename))

    total_files = len(files_to_scan)
    print(f"Found {total_files} files to analyze.")

    # Set to store unique combinations of (SNI, Algorithm)
    seen_combinations = set()

    with open(output_csv, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)

        # 2. Iterate with index
        for i, full_path in enumerate(files_to_scan, 1):
            filename = os.path.basename(full_path)

            # UPDATED PRINT STATEMENT
            print(f"[{i}/{total_files}] Analyzing: {full_path}...")

            try:
                # Pass the seen_combinations set to the processor
                rows = process_pcap(full_path, filename, seen_combinations)

                if rows:
                    writer.writerows(rows)
                    print(f" -> Added {len(rows)} new unique entries.")
                else:
                    # Optional: Comment out to reduce noise if you prefer
                    print(" -> No new unique PQC/TLS entries found.")

            except Exception as e:
                print(f"Error processing {filename}: {e}")

    print(f"\nAnalysis complete. Results saved to {output_csv}")


def process_pcap(file_path, filename, seen_combinations):
    results = []

    # Filter for Client Hello (1) and Server Hello (2)
    display_filter = 'tls.handshake.type == 1 || tls.handshake.type == 2'

    # Map TCP Stream Index -> SNI
    stream_sni_map = {}

    cap = pyshark.FileCapture(file_path, display_filter=display_filter, keep_packets=False)

    try:
        for pkt in cap:
            try:
                # Identify Stream Index
                if hasattr(pkt, 'tcp'):
                    stream_index = pkt.tcp.stream
                elif hasattr(pkt, 'udp'):  # QUIC often uses UDP
                    stream_index = pkt.udp.stream
                else:
                    continue

                if not hasattr(pkt, 'tls'):
                    continue

                tls_layer = pkt.tls
                handshake_type = getattr(tls_layer, 'handshake_type', None)

                # --- CLIENT HELLO: Grab SNI ---
                if handshake_type == '1':
                    sni = getattr(tls_layer, 'handshake_extensions_server_name', None)
                    if sni:
                        stream_sni_map[stream_index] = sni

                # --- SERVER HELLO: Grab Algo ---
                elif handshake_type == '2':
                    # Get Raw ID
                    raw_group = getattr(tls_layer, 'handshake_extensions_key_share_group', None)

                    if raw_group:
                        # Resolve to Human Readable Name
                        algo_name = resolve_group_name(raw_group)

                        # Retrieve SNI
                        sni_name = stream_sni_map.get(stream_index, "Unknown SNI")

                        # --- DEDUPLICATION LOGIC ---
                        if sni_name != "Unknown SNI":
                            combo = (sni_name, algo_name)

                            # If we have seen this Domain + Algo combination before, SKIP it.
                            if combo in seen_combinations:
                                continue

                            # Mark as seen
                            seen_combinations.add(combo)

                            # Get IPs
                            if 'IP' in pkt:
                                src_ip, dst_ip = pkt.ip.src, pkt.ip.dst
                            elif 'IPv6' in pkt:
                                src_ip, dst_ip = pkt.ipv6.src, pkt.ipv6.dst
                            else:
                                src_ip, dst_ip = "Unknown", "Unknown"

                            results.append([
                                filename,
                                pkt.number,
                                sni_name,
                                algo_name,
                                src_ip,
                                dst_ip
                            ])

            except AttributeError:
                continue
    finally:
        cap.close()

    return results


if __name__ == "__main__":
    SEARCH_DIRECTORY = 'C:\\Users\\shake\\Downloads\\122\\122'
    OUTPUT_FILE = 'pqc_unique_domains_mlkem_without_audio_video.csv'

    analyze_pcap_files(SEARCH_DIRECTORY, OUTPUT_FILE)