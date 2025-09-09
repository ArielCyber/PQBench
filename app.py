from flask import Flask, render_template, request
import subprocess

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("Main_page.html")

@app.route("/run_kyber", methods=["POST"])
def run_kyber():
    try:
        # הפעלת סקריפט חישוב kyber
        result = subprocess.check_output(["python", "processorKyber.py"])
        return f"<pre>{result.decode()}</pre>"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
