#!/usr/bin/env python
"""
Start backend with Gemini API key from environment
"""

import os
import subprocess
import sys

# Set Gemini API key
API_KEY = "AIzaSyBIFpQCr_wTSC1TN6tYlwJsbQ_mu7uQJ-w"
os.environ["GEMINI_API_KEY"] = API_KEY

print(f"[INFO] GEMINI_API_KEY set: {bool(os.environ.get('GEMINI_API_KEY'))}")
print(f"[INFO] Starting backend with Gemini support...\n")

# Start uvicorn
cmd = [
    sys.executable, "-m", "uvicorn",
    "main:app",
    "--host", "0.0.0.0",
    "--port", "8000",
    "--log-level", "info"
]

print(f"[INFO] Running: {' '.join(cmd)}\n")

try:
    subprocess.run(cmd, cwd="d:\\Projects\\kle asteria\\kle sheshgiri\\backend")
except KeyboardInterrupt:
    print("\n[INFO] Shutdown requested")
except Exception as e:
    print(f"[ERROR] {e}")
    sys.exit(1)
