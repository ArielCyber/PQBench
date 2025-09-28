#!/bin/bash

echo "Starting PQC Processor..."

source venv/bin/activate

MODE="${MODE:-KYBER}"

echo "Running with MODE=$MODE"

MODE="$MODE" python3 processor.py
