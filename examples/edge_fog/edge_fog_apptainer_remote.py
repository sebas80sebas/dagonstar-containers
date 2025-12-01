#!/usr/bin/env python3
"""
Simplified Dagon workflow for DHT sensor capture from Arduino + remote preprocessing.
Includes preliminary step for granting permissions to /dev/ttyACM0 port.
"""

import json, configparser, logging
from dagon import Workflow
from dagon.task import DagonTask, TaskType


# --- Read SSH configuration ---
config = configparser.ConfigParser()
config.read('dagon.ini')
RASPI_IP   = config.get('ssh', 'raspi_ip')
RASPI_USER = config.get('ssh', 'raspi_user')
RASPI_PORT = config.getint('ssh', 'raspi_port')


# --- Create workflow ---
workflow = Workflow("DHT-Sensor-Capture-And-Preprocess")


# ========== TASK A: DHT Sensor Capture ==========
taskA_command = """
# ========== Initial Setup ==========
LOG_FILE="/home/raspi/dagon_capture_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "Starting DHT sensor capture"
echo "Date: $(date)"
echo "=========================================="

# --- Install pyserial ---
echo "Installing pyserial..."
pip install --no-cache-dir pyserial >/dev/null 2>&1

# --- Inline Python script ---
python3 << 'EOF'
import serial, re, json, time, os

# Serial port configuration
PORT = '/dev/ttyACM0'
BAUDRATE = 9600
DURATION = 30
OUTPUT_FILE = 'output.json'

print(f"Configuration:\\n  Port: {PORT}\\n  Duration: {DURATION}s")

# Check if port exists
if not os.path.exists(PORT):
    print(f"ERROR: Port {PORT} not found")
    json.dump({'error': 'Port not found', 'timestamp': time.time()}, open(OUTPUT_FILE, 'w'), indent=2)
    exit(1)

try:
    # Initialize serial connection
    ser = serial.Serial(PORT, BAUDRATE, timeout=2)
    print(f"Port {PORT} opened successfully\\n")
    data, start = [], time.time()

    # Main capture loop
    while time.time() - start < DURATION:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line:
            continue
        print(f" {line}")
        # Extract temperature and humidity values
        m = re.search(r'Humidity:\\s*([\\d.]+).*Temperature:\\s*([\\d.]+)', line)
        if m:
            data.append({'timestamp': time.time(), 'humidity': float(m[1]), 'temp_c': float(m[2])})

    # Close connection and save data
    ser.close()
    json.dump(data, open(OUTPUT_FILE, 'w'), indent=2)
    print(f" Data saved to {OUTPUT_FILE} ({len(data)} records)")

except Exception as e:
    # Handle errors
    json.dump({'error': str(e), 'timestamp': time.time()}, open(OUTPUT_FILE, 'w'), indent=2)
    print(f"ERROR: {e}")
    exit(1)

print("Capture completed successfully")
EOF

# --- Save results ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="/home/raspi/sensor_output_${TIMESTAMP}.json"
cp output.json "$DEST" 2>/dev/null || echo '{"error":"output.json not created"}' > "$DEST"

echo "=========================================="
echo "Log saved to: $LOG_FILE"
echo "Results saved to: $DEST"
echo "=========================================="
"""

# Create task A with Apptainer settings
taskA = DagonTask(
    TaskType.APPTAINER,
    "A",
    taskA_command,
    image="docker://python:3.9-slim",
    ip=RASPI_IP,
    ssh_username=RASPI_USER,
    ssh_port=RASPI_PORT
)

# Set additional arguments for hardware access
taskA.extra_args = [
    "--security=cap-add=ALL",
    "--bind", "/dev/ttyACM0:/dev/ttyACM0",
    "--bind", "/home/raspi:/home/raspi",
    "--writable-tmpfs"
]

workflow.add_task(taskA)


# ========== TASK B: Remote Preprocessing ==========
taskB_command = """
# ========== Preprocessing Setup ==========
LOG_FILE="/home/raspi/dagon_preprocess_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "Starting preprocessing"
echo "Date: $(date)"
echo "=========================================="

# --- Install requirements ---
echo "Installing pandas..."
pip install --no-cache-dir pandas >/dev/null 2>&1

# --- Inline Python script for preprocessing ---
python3 << 'EOF'
import json, glob, os
import pandas as pd

# Buscar el último archivo capturado
files = sorted(glob.glob('/home/raspi/sensor_output_*.json'))
if not files:
    print("ERROR: No sensor_output files found")
    exit(1)

input_file = files[-1]
output_file = input_file.replace('.json', '_preprocessed.json')

print(f"Processing: {input_file}")

# Leer datos
with open(input_file) as f:
    data = json.load(f)

# Si el archivo contiene un dict de error, abortar
if isinstance(data, dict) and 'error' in data:
    print(f\"ERROR in input file: {data['error']}\")
    exit(1)

df = pd.DataFrame(data)

if df.empty or 'humidity' not in df or 'temp_c' not in df:
    print("ERROR: No data to process or missing keys")
    exit(1)

summary = {
    "count": int(len(df)),
    "mean_humidity": float(df["humidity"].mean()),
    "mean_temp_c": float(df["temp_c"].mean()),
    "min_humidity": float(df["humidity"].min()),
    "max_humidity": float(df["humidity"].max()),
    "min_temp_c": float(df["temp_c"].min()),
    "max_temp_c": float(df["temp_c"].max()),
    "start_time": float(df["timestamp"].min()),
    "end_time": float(df["timestamp"].max())
}

with open(output_file, 'w') as out:
    json.dump({"summary": summary, "raw": data}, out, indent=2)

print(f"Preprocessed file saved to {output_file}")
EOF

echo "=========================================="
echo "Log saved to: $LOG_FILE"
echo "=========================================="
"""

taskB = DagonTask(
    TaskType.APPTAINER,
    "B",
    taskB_command,
    image="docker://python:3.9-slim",
    ip=RASPI_IP,
    ssh_username=RASPI_USER,
    ssh_port=RASPI_PORT
)

taskB.extra_args = [
    "--security=cap-add=ALL",
    "--bind", "/home/raspi:/home/raspi",
    "--writable-tmpfs"
]

workflow.add_task(taskB)

workflow.make_dependencies()
# --- Save workflow configuration ---
with open('dht_sensor_workflow.json', 'w') as f:
    json.dump(workflow.as_json(), f, indent=2)
print("Workflow saved: dht_sensor_workflow.json")


# --- Setup logging and execution ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')

print("\n" + "="*60)
print("Starting DHT Sensor Capture + Preprocess with Dagon")
print("="*60)
print(f"Raspberry Pi: {RASPI_IP}")
print(f"Device: /dev/ttyACM0 (Arduino)")
print(f"Duration: 30 seconds")
print(f"Logs: /home/raspi/dagon_capture_*.log and /home/raspi/dagon_preprocess_*.log")
print(f"Raw Output: /home/raspi/sensor_output_*.json")
print(f"Preprocessed: /home/raspi/sensor_output_*_preprocessed.json")
print("="*60 + "\n")

# Execute workflow
workflow.run()

print("\nWorkflow completed successfully")
print("Raw and preprocessed results saved in /home/raspi/")
print("You can check them using, for example:")
print(f"ssh {RASPI_USER}@{RASPI_IP} 'ls -1 /home/raspi/sensor_output_*.json'")
print("="*60 + "\n")
