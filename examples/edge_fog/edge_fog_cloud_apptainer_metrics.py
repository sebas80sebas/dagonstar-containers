#!/usr/bin/env python3
"""
Dagon DHT Workflow with energy metrics capture
Integrates: DHT sensor + MongoDB + Prometheus energy metrics
"""

import json, configparser, logging, time
from dagon import Workflow
from dagon.task import DagonTask, TaskType
from datetime import datetime
from pymongo import MongoClient
import sys
import os
import subprocess

# Import metrics collector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from energy_metrics_collector import PrometheusMetricsCollector

# --- Read configuration ---
config = configparser.ConfigParser()
config.read('dagon.ini')

RASPI_IP = config.get('ssh', 'raspi_ip')
RASPI_USER = config.get('ssh', 'raspi_user')
RASPI_PORT = config.getint('ssh', 'raspi_port')

MONGO_URI = config.get('mongodb', 'uri')
MONGO_DB = config.get('mongodb', 'database')
MONGO_COLLECTION = config.get('mongodb', 'collection')

PROMETHEUS_URL = config.get('prometheus', 'url', fallback='http://localhost:9090')
SAMPLING_INTERVAL = config.getint('prometheus', 'sampling_interval', fallback=2)

# --- Generate execution ID ---
EXECUTION_ID = time.strftime("%Y%m%d_%H%M%S")

print("="*70)
print("Dagon DHT Workflow with Energy Monitoring")
print("="*70)
print(f"Execution ID: {EXECUTION_ID}")
print(f"Raspberry Pi: {RASPI_IP}")
print(f"MongoDB: {MONGO_URI}")
print(f"Prometheus: {PROMETHEUS_URL}")
print(f"Sampling: every {SAMPLING_INTERVAL}s")
print("="*70 + "\n")

# --- Create workflow ---
workflow = Workflow("DHT-Sensor-Capture-And-Preprocess")

# ========== TASK A: DHT Sensor Capture ==========
taskA_command = f"""
# ========== Initial Setup ==========
TASK="A"
WORKFLOW="DHT-Sensor-Capture-And-Preprocess"
EXECUTION_ID="{EXECUTION_ID}"

# Metrics paths
METRICS_TMP="/tmp/dagon_${{TASK}}.prom"
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
METRICS_CURRENT="${{METRICS_DIR}}/dagon_dht_${{TASK}}_current.prom"
METRICS_HISTORY="/home/raspi/.dagon_metrics/history/dagon_dht_${{TASK}}_${{EXECUTION_ID}}.prom"
METRICS_BACKUP="/home/raspi/.dagon_metrics/dagon_dht_${{TASK}}.prom"

START_TS=$(date +%s.%N)
SUCCESS=1
RECORDS=0

LOG_FILE="/home/raspi/dagon_capture_${{EXECUTION_ID}}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "Starting DHT sensor capture"
echo "Execution ID: ${{EXECUTION_ID}}"
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

print(f"Configuration:\\n  Port: {{PORT}}\\n  Duration: {{DURATION}}s")

# Check if port exists
if not os.path.exists(PORT):
    print(f"ERROR: Port {{PORT}} not found")
    json.dump({{'error': 'Port not found', 'timestamp': time.time()}}, open(OUTPUT_FILE, 'w'), indent=2)
    exit(1)

try:
    # Initialize serial connection
    ser = serial.Serial(PORT, BAUDRATE, timeout=2)
    print(f"Port {{PORT}} opened successfully\\n")
    print("Starting DHT11 sensor reading...")
    data, start = [], time.time()

    # Main capture loop
    while time.time() - start < DURATION:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line:
            continue
        print(f"{{line}}")
        # Extract temperature and humidity values
        m = re.search(r'Humidity:\\s*([\\d.]+).*Temperature:\\s*([\\d.]+)', line)
        if m:
            data.append({{'timestamp': time.time(), 'humidity': float(m[1]), 'temp_c': float(m[2])}})

    # Close connection and save data
    ser.close()
    print(f"RECORDS_CAPTURED={{len(data)}}")
    json.dump(data, open(OUTPUT_FILE, 'w'), indent=2)
    print(f"Data saved to {{OUTPUT_FILE}} ({{len(data)}} records)")

except Exception as e:
    # Handle errors
    json.dump({{'error': str(e), 'timestamp': time.time()}}, open(OUTPUT_FILE, 'w'), indent=2)
    print(f"ERROR: {{e}}")
    exit(1)

print("Capture completed successfully")
EOF

# --- Save results with execution ID ---
DEST="/home/raspi/sensor_output_${{EXECUTION_ID}}.json"
cp output.json "$DEST" 2>/dev/null || echo '{{"error":"output.json not created"}}' > "$DEST"

echo "=========================================="
echo "Log saved to: $LOG_FILE"
echo "Results saved to: $DEST"

END_TS=$(date +%s.%N)
DURATION=$(awk "BEGIN {{print ${{END_TS}}-${{START_TS}}}}")

# Extract number of records
RECORDS=$(grep -o "RECORDS_CAPTURED=[0-9]*" "$LOG_FILE" | tail -1 | cut -d= -f2)
RECORDS=${{RECORDS:-0}}

# Check for errors
grep -q "ERROR" "$LOG_FILE" && SUCCESS=0

# Write metrics with execution_id label (ATOMIC)
cat <<EOF_METRICS > ${{METRICS_TMP}}
# HELP dagon_task_duration_seconds Duration of a Dagon task
# TYPE dagon_task_duration_seconds gauge
dagon_task_duration_seconds{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{DURATION}}

# HELP dagon_task_success Task success (1=success, 0=failure)
# TYPE dagon_task_success gauge
dagon_task_success{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{SUCCESS}}

# HELP dagon_task_records_total Records processed by task
# TYPE dagon_task_records_total gauge
dagon_task_records_total{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{RECORDS}}

# HELP dagon_execution_start_timestamp_seconds Start timestamp of execution
# TYPE dagon_execution_start_timestamp_seconds gauge
dagon_execution_start_timestamp_seconds{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{START_TS}}
EOF_METRICS

# 1. Save to HISTORY (never overwritten - for MongoDB export)
mkdir -p $(dirname ${{METRICS_HISTORY}})
cp ${{METRICS_TMP}} ${{METRICS_HISTORY}}
echo "Metrics history saved: ${{METRICS_HISTORY}}"

# 2. Save to BACKUP (overwritten - for quick access)
mkdir -p $(dirname ${{METRICS_BACKUP}})
cp ${{METRICS_TMP}} ${{METRICS_BACKUP}}
echo "Metrics backup saved: ${{METRICS_BACKUP}}"

# 3. Publish to Prometheus (overwritten - Prometheus scrapes periodically)
if [ -d "${{METRICS_DIR}}" ]; then
    cp ${{METRICS_TMP}} ${{METRICS_CURRENT}} 2>/dev/null && echo "Metrics published to Prometheus: ${{METRICS_CURRENT}}" || echo "Warning: Could not publish to Prometheus"
fi

# Save EXECUTION_ID for subsequent tasks
echo "${{EXECUTION_ID}}" > /home/raspi/.dagon_metrics/current_execution_id

echo "=========================================="
"""

taskA = DagonTask(
    TaskType.APPTAINER,
    "A",
    taskA_command,
    image="docker://python:3.9-slim",
    ip=RASPI_IP,
    ssh_username=RASPI_USER,
    ssh_port=RASPI_PORT
)

taskA.extra_args = [
    "--bind", "/dev/ttyACM0:/dev/ttyACM0",
    "--bind", "/home/raspi:/home/raspi",
    "--bind", "/var/lib/node_exporter:/var/lib/node_exporter:rw",
    "--writable-tmpfs"
]

workflow.add_task(taskA)


# ========== TASK B: Remote Preprocessing ==========
taskB_command = f"""
# ========== Preprocessing Setup ==========
TASK="B"
WORKFLOW="DHT-Sensor-Capture-And-Preprocess"

# Read execution ID from Task A
EXECUTION_ID=$(cat /home/raspi/.dagon_metrics/current_execution_id 2>/dev/null || echo "{EXECUTION_ID}")

# Metrics paths
METRICS_TMP="/tmp/dagon_${{TASK}}.prom"
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
METRICS_CURRENT="${{METRICS_DIR}}/dagon_dht_${{TASK}}_current.prom"
METRICS_HISTORY="/home/raspi/.dagon_metrics/history/dagon_dht_${{TASK}}_${{EXECUTION_ID}}.prom"
METRICS_BACKUP="/home/raspi/.dagon_metrics/dagon_dht_${{TASK}}.prom"

START_TS=$(date +%s.%N)
SUCCESS=1
RECORDS=0

LOG_FILE="/home/raspi/dagon_preprocess_${{EXECUTION_ID}}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "Starting preprocessing"
echo "Execution ID: ${{EXECUTION_ID}}"
echo "Date: $(date)"
echo "=========================================="

# --- Install requirements ---
echo "Installing pandas..."
pip install --no-cache-dir pandas >/dev/null 2>&1

# --- Inline Python script for preprocessing ---
python3 << 'EOF'
import json, glob, os, time
import pandas as pd

# Read execution ID
with open('/home/raspi/.dagon_metrics/current_execution_id') as f:
    execution_id = f.read().strip()

# Wait a bit to ensure file is fully written
time.sleep(2)

# Search for the file from this execution
input_file = f'/home/raspi/sensor_output_{{execution_id}}.json'
output_file = input_file.replace('.json', '_preprocessed.json')

if not os.path.exists(input_file):
    print(f"ERROR: Input file not found: {{input_file}}")
    exit(1)

print(f"Processing: {{input_file}}")

# Read data
with open(input_file) as f:
    data = json.load(f)

# If the file contains an error dict, abort
if isinstance(data, dict) and 'error' in data:
    print(f"ERROR in input file: {{data['error']}}")
    exit(1)

df = pd.DataFrame(data)

if df.empty or 'humidity' not in df or 'temp_c' not in df:
    print("ERROR: No data to process or missing keys")
    exit(1)

summary = {{
    "count": int(len(df)),
    "mean_humidity": float(df["humidity"].mean()),
    "mean_temp_c": float(df["temp_c"].mean()),
    "min_humidity": float(df["humidity"].min()),
    "max_humidity": float(df["humidity"].max()),
    "min_temp_c": float(df["temp_c"].min()),
    "max_temp_c": float(df["temp_c"].max()),
    "start_time": float(df["timestamp"].min()),
    "end_time": float(df["timestamp"].max())
}}

print(f"RECORDS_CAPTURED={{summary['count']}}")
print(f"  Mean Humidity: {{summary['mean_humidity']:.2f}}%")
print(f"  Mean Temp: {{summary['mean_temp_c']:.2f}}C")

with open(output_file, 'w') as out:
    json.dump({{"execution_id": execution_id, "summary": summary, "raw": data}}, out, indent=2)

print(f"Preprocessed file saved to {{output_file}}")
print("Preprocessing completed successfully")
EOF

echo "=========================================="
echo "Log saved to: $LOG_FILE"

END_TS=$(date +%s.%N)
DURATION=$(awk "BEGIN {{print ${{END_TS}}-${{START_TS}}}}")

# Extract number of records
RECORDS=$(grep -o "RECORDS_CAPTURED=[0-9]*" "$LOG_FILE" | tail -1 | cut -d= -f2)
RECORDS=${{RECORDS:-0}}

# Check for errors
grep -q "ERROR" "$LOG_FILE" && SUCCESS=0

# Write metrics with execution_id label (ATOMIC)
cat <<EOF_METRICS > ${{METRICS_TMP}}
# HELP dagon_task_duration_seconds Duration of a Dagon task
# TYPE dagon_task_duration_seconds gauge
dagon_task_duration_seconds{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{DURATION}}

# HELP dagon_task_success Task success (1=success, 0=failure)
# TYPE dagon_task_success gauge
dagon_task_success{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{SUCCESS}}

# HELP dagon_task_records_total Records processed by task
# TYPE dagon_task_records_total gauge
dagon_task_records_total{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{RECORDS}}

# HELP dagon_execution_start_timestamp_seconds Start timestamp of execution
# TYPE dagon_execution_start_timestamp_seconds gauge
dagon_execution_start_timestamp_seconds{{workflow="${{WORKFLOW}}",task="${{TASK}}",execution_id="${{EXECUTION_ID}}"}} ${{START_TS}}
EOF_METRICS

# 1. Save to HISTORY (never overwritten)
mkdir -p $(dirname ${{METRICS_HISTORY}})
cp ${{METRICS_TMP}} ${{METRICS_HISTORY}}
echo "Metrics history saved: ${{METRICS_HISTORY}}"

# 2. Save to BACKUP (overwritten)
mkdir -p $(dirname ${{METRICS_BACKUP}})
cp ${{METRICS_TMP}} ${{METRICS_BACKUP}}
echo "Metrics backup saved: ${{METRICS_BACKUP}}"

# 3. Publish to Prometheus (overwritten)
if [ -d "${{METRICS_DIR}}" ]; then
    cp ${{METRICS_TMP}} ${{METRICS_CURRENT}} 2>/dev/null && echo "Metrics published to Prometheus: ${{METRICS_CURRENT}}" || echo "Warning: Could not publish to Prometheus"
fi

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
    "--no-home",
    "--bind", "/home/raspi:/home/raspi",
    "--bind", "/var/lib/node_exporter:/var/lib/node_exporter:rw",
    "--writable-tmpfs"
]

workflow.add_task(taskB)
taskB.add_dependency_to(taskA)


# ========== TASK C: Export to MongoDB ==========
taskC_command = f"""
# ========== MongoDB Export Setup ==========
TASK="C"
WORKFLOW="DHT-Sensor-Capture-And-Preprocess"

# Read execution ID
EXECUTION_ID=$(cat /home/raspi/.dagon_metrics/current_execution_id 2>/dev/null || echo "{EXECUTION_ID}")

START_TS=$(date +%s.%N)
SUCCESS=1

LOG_FILE="/home/raspi/dagon_mongodb_export_${{EXECUTION_ID}}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "Starting MongoDB export"
echo "Execution ID: ${{EXECUTION_ID}}"
echo "Date: $(date)"
echo "MongoDB: {MONGO_URI}"
echo "=========================================="

# --- Install pymongo ---
echo "Installing pymongo..."
pip install --no-cache-dir pymongo >/dev/null 2>&1

# --- Inline Python script for MongoDB export ---
python3 << 'PYEOF'
import json, re, time, os
from pymongo import MongoClient
from datetime import datetime

# Read execution ID
with open('/home/raspi/.dagon_metrics/current_execution_id') as f:
    execution_id = f.read().strip()

# MongoDB configuration (from host)
MONGO_URI = "{MONGO_URI}"
MONGO_DB = "{MONGO_DB}"
MONGO_COLLECTION = "{MONGO_COLLECTION}"
RASPI_IP = "{RASPI_IP}"

print(f"Execution ID: {{execution_id}}")
print(f"Connecting to MongoDB: {{MONGO_URI}}")

try:
    # Connect to MongoDB (REMOTE)
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[MONGO_DB]
    collection = db[MONGO_COLLECTION]
    
    # Test connection
    client.server_info()
    print("MongoDB connection successful")
    
    # Check if this execution already exists
    if collection.find_one({{"execution_id": execution_id}}):
        print(f"Warning: Execution {{execution_id}} already exported to MongoDB")
        exit(0)
    
    # Find preprocessed file for this execution
    preprocessed_file = f'/home/raspi/sensor_output_{{execution_id}}_preprocessed.json'
    
    if not os.path.exists(preprocessed_file):
        print(f"ERROR: Preprocessed file not found: {{preprocessed_file}}")
        exit(1)
    
    print(f"Reading: {{preprocessed_file}}")
    
    with open(preprocessed_file) as f:
        data = json.load(f)
    
    # Parse metrics from HISTORY files
    def parse_prometheus_metrics(metric_file):
        metrics = {{}}
        try:
            with open(metric_file) as f:
                for line in f:
                    if line.startswith('#') or not line.strip():
                        continue
                    # Extract metric name and value
                    match = re.search(r'(\\w+)\\{{.*task="(\\w+)".*\\}}\\s+([\\d.]+)', line)
                    if match:
                        metric_name, task, value = match.groups()
                        key = metric_name.replace('dagon_', '').replace('_seconds', '')
                        metrics[f'task_{{task}}_{{key}}'] = float(value)
        except Exception as e:
            print(f"Warning: Could not read metrics from {{metric_file}}: {{e}}")
        return metrics
    
    # Read metrics from history files
    metrics = {{}}
    for task in ['A', 'B']:
        metric_file = f'/home/raspi/.dagon_metrics/history/dagon_dht_{{task}}_{{execution_id}}.prom'
        metrics.update(parse_prometheus_metrics(metric_file))
    
    # Calculate total duration
    total_duration = metrics.get('task_A_task_duration', 0) + metrics.get('task_B_task_duration', 0)
    
    # Build document to insert
    document = {{
        "execution_id": execution_id,
        "workflow": "DHT-Sensor-Capture-And-Preprocess",
        "export_timestamp": datetime.utcnow(),
        "raspberry_pi": RASPI_IP,
        "summary": data.get("summary", {{}}),
        "metrics": metrics,
        "total_duration_seconds": total_duration,
        "raw_data_count": len(data.get("raw", [])),
        "source_file": preprocessed_file,
        "all_tasks_successful": (
            metrics.get('task_A_task_success', 0) == 1 and 
            metrics.get('task_B_task_success', 0) == 1
        )
    }}
    
    # Insert into MongoDB
    result = collection.insert_one(document)
    print(f"Document inserted with ID: {{result.inserted_id}}")
    print(f"  Records: {{data['summary']['count']}}")
    print(f"  Mean temp: {{data['summary']['mean_temp_c']:.2f}}C")
    print(f"  Mean humidity: {{data['summary']['mean_humidity']:.2f}}%")
    print(f"  Total duration: {{total_duration:.2f}}s")
    
    # Show collection stats
    total_docs = collection.count_documents({{}})
    print(f"\\nTotal executions in MongoDB: {{total_docs}}")
    
    print("\\nMongoDB export completed successfully")
    
except Exception as e:
    print(f"ERROR: {{e}}")
    import traceback
    traceback.print_exc()
    exit(1)
finally:
    client.close()

PYEOF

echo "=========================================="
echo "Log saved to: $LOG_FILE"
echo "=========================================="
"""

taskC = DagonTask(
    TaskType.APPTAINER,
    "C",
    taskC_command,
    image="docker://python:3.9-slim",
    ip=RASPI_IP,
    ssh_username=RASPI_USER,
    ssh_port=RASPI_PORT
)

taskC.extra_args = [
    "--no-home",
    "--bind", "/home/raspi:/home/raspi",
    "--writable-tmpfs"
]

workflow.add_task(taskC)
taskC.add_dependency_to(taskB)


# ========== WORKFLOW EVENT FUNCTIONS ==========
def write_workflow_event(metric_name, workflow_name, execution_id):
    """
    Writes a point-in-time metric for Prometheus on the Raspberry Pi via SSH
    """
    metrics_dir = "/var/lib/node_exporter/textfile_collector"
    tmp_file = f"/tmp/{metric_name}.prom"
    final_file = f"{metrics_dir}/{metric_name}.prom"
    
    # Use current timestamp in milliseconds
    timestamp = int(time.time() * 1000)
    
    metric = f"""# HELP {metric_name} Dagon workflow event
# TYPE {metric_name} gauge
{metric_name}{{workflow="{workflow_name}",execution_id="{execution_id}"}} {timestamp}
"""
    
    try:
        # Build SSH command to write metric on Raspberry Pi
        ssh_cmd = [
            'ssh',
            '-p', str(RASPI_PORT),
            f'{RASPI_USER}@{RASPI_IP}',
            f"cat > {tmp_file} << 'EOF'\n{metric}EOF\nmv {tmp_file} {final_file} && chmod 644 {final_file}"
        ]
        
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print(f"Workflow event published: {metric_name}")
            print(f"  Timestamp: {timestamp}")
        else:
            print(f"Warning: Could not write workflow event {metric_name}")
            if result.stderr:
                print(f"  Error: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        print(f"Timeout writing workflow event {metric_name}")
    except Exception as e:
        print(f"Could not write workflow event {metric_name}: {e}")


# --- Configure logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')

# ========== INTEGRATION WITH ENERGY MONITORING ==========

# 1. Create metrics collector
energy_collector = PrometheusMetricsCollector(
    prometheus_url=PROMETHEUS_URL,
    sampling_interval=SAMPLING_INTERVAL
)

print("Starting energy monitoring...")
energy_collector.start_collection()

# 2. Execute workflow
print(f"\nExecuting workflow (Tasks A, B, C)...\n")

# ===== WORKFLOW START EVENT =====
write_workflow_event(
    metric_name="dagon_workflow_start",
    workflow_name=workflow.name,
    execution_id=EXECUTION_ID
)

workflow_start = time.time()

try:
    workflow.run()
    workflow_success = True
except Exception as e:
    print(f"Error in workflow: {e}")
    workflow_success = False

# ===== WORKFLOW END EVENT =====
write_workflow_event(
    metric_name="dagon_workflow_end",
    workflow_name=workflow.name,
    execution_id=EXECUTION_ID
)

workflow_end = time.time()
workflow_duration = workflow_end - workflow_start

# 3. Stop metrics collection
print(f"\nStopping energy monitoring...")
energy_collector.stop_collection()

# 4. Get statistics
energy_stats = energy_collector.calculate_statistics()
energy_collector.print_summary()

# 5. Export metrics to local file
energy_filename = f"energy_metrics_{EXECUTION_ID}.json"
energy_collector.export_to_json(energy_filename)

# ========== EXPORT EVERYTHING TO MONGODB ==========
print("\n" + "="*70)
print("Adding energy metrics to MongoDB...")
print("="*70)

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[MONGO_DB]
    collection = db[MONGO_COLLECTION]
    
    # Verify connection
    client.server_info()
    print("Connected to MongoDB")
    
    # Find the document that Task C inserted
    workflow_doc = collection.find_one({"execution_id": EXECUTION_ID})
    
    if workflow_doc:
        print(f"Found workflow document")
        
        # Add energy metrics to document
        update_data = {
            "$set": {
                "energy_monitoring": {
                    "enabled": True,
                    "prometheus_url": PROMETHEUS_URL,
                    "sampling_interval_seconds": SAMPLING_INTERVAL,
                    "collection_duration_seconds": energy_stats.get('collection_duration_seconds', 0),
                    "samples_count": energy_stats.get('samples_count', 0),
                    
                    # Raspberry Pi metrics
                    "raspberry_pi": {
                        "power": {
                            "mean_watts": energy_stats.get('rpi_power_watts_mean', 0),
                            "max_watts": energy_stats.get('rpi_power_watts_max', 0),
                            "min_watts": energy_stats.get('rpi_power_watts_min', 0),
                            "std_watts": energy_stats.get('rpi_power_watts_std', 0)
                        },
                        "cpu": {
                            "mean_percent": energy_stats.get('rpi_cpu_percent_mean', 0),
                            "max_percent": energy_stats.get('rpi_cpu_percent_max', 0)
                        },
                        "ram": {
                            "mean_percent": energy_stats.get('rpi_ram_percent_mean', 0),
                            "max_percent": energy_stats.get('rpi_ram_percent_max', 0)
                        },
                        "temperature": {
                            "mean_celsius": energy_stats.get('rpi_temp_celsius_mean', 0),
                            "max_celsius": energy_stats.get('rpi_temp_celsius_max', 0)
                        },
                        "energy": {
                            "total_joules": energy_stats.get('rpi_energy_joules', 0),
                            "total_wh": energy_stats.get('rpi_energy_wh', 0)
                        }
                    },
                    
                    # PC metrics (if they exist)
                    "pc": {
                        "power": {
                            "mean_watts": energy_stats.get('pc_power_watts_mean', 0),
                            "max_watts": energy_stats.get('pc_power_watts_max', 0),
                            "min_watts": energy_stats.get('pc_power_watts_min', 0),
                            "std_watts": energy_stats.get('pc_power_watts_std', 0)
                        },
                        "cpu": {
                            "mean_percent": energy_stats.get('pc_cpu_percent_mean', 0),
                            "max_percent": energy_stats.get('pc_cpu_percent_max', 0)
                        },
                        "ram": {
                            "mean_percent": energy_stats.get('pc_ram_percent_mean', 0),
                            "max_percent": energy_stats.get('pc_ram_percent_max', 0)
                        },
                        "temperature": {
                            "mean_celsius": energy_stats.get('pc_temp_celsius_mean', 0),
                            "max_celsius": energy_stats.get('pc_temp_celsius_max', 0)
                        },
                        "energy": {
                            "total_joules": energy_stats.get('pc_energy_joules', 0),
                            "total_wh": energy_stats.get('pc_energy_wh', 0)
                        }
                    } if 'pc_power_watts_mean' in energy_stats else {},
                },
                
                # Add update timestamp
                "energy_metrics_added_at": datetime.utcnow()
            }
        }
        
        # Update document
        result = collection.update_one(
            {"execution_id": EXECUTION_ID},
            update_data
        )
        
        print(f"Energy metrics added to document")
        print(f"   RasPi Energy: {energy_stats.get('rpi_energy_wh', 0):.4f} Wh")
        if 'pc_energy_wh' in energy_stats:
            print(f"   PC Energy: {energy_stats.get('pc_energy_wh', 0):.4f} Wh")
        
    else:
        print(f"Warning: Workflow document not found")
        print("    This can happen if Task C failed or did not complete")
    
    client.close()
    
except Exception as e:
    print(f"Error exporting to MongoDB: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("WORKFLOW COMPLETED")
print("="*70)
print(f"Total duration: {workflow_duration:.2f}s")
print(f"RasPi Energy: {energy_stats.get('rpi_energy_wh', 0):.4f} Wh")
if 'pc_energy_wh' in energy_stats:
    print(f"PC Energy: {energy_stats.get('pc_energy_wh', 0):.4f} Wh")
print(f"\nLocal metrics: {energy_filename}")
print(f"MongoDB: {MONGO_DB}.{MONGO_COLLECTION}")
print(f"Analyze: python3 energy_analysis_tools.py summary 1")
print("="*70 + "\n")