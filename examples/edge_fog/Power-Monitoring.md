# Power Monitor Setup Guide

This guide explains how to set up and run the power monitoring script on a Raspberry Pi to measure power consumption during workflow execution.

## Prerequisites

- Raspberry Pi with SSH access
- `power_monitor.sh` script
- Python 3 installed on your local PC
- `dagon_workflow.py` script on your local PC

## Setup Instructions

### 1. Upload the Script to Raspberry Pi

Copy the `power_monitor.sh` script to your Raspberry Pi:

```bash
scp power_monitor.sh raspi@RASPI_IP:/home/raspi/
```

### 2. Grant Execution Permissions

SSH into your Raspberry Pi and make the script executable:

```bash
chmod +x power_monitor.sh
```

### 3. Start the Power Monitor in Background

From your local PC, start the monitoring process in the background:

```bash
ssh raspi@RASPI_IP "nohup ./power_monitor.sh > /home/raspi/power_live.log 2>&1 &"
```

This command:
- Runs the monitor script in the background using `nohup`
- Redirects output to `/home/raspi/power_live.log`
- Continues running even after SSH disconnection

### 4. Execute the Workflow

Run your workflow from your local PC:

```bash
python3 dagon_workflow.py
```

### 5. View Results

After the monitoring period completes, check the results on the Raspberry Pi:

```bash
ssh raspi@RASPI_IP "cat /home/raspi/power_live.log"
```

## Expected Output

```
nohup: ignoring input
Monitoreo iniciado durante 50 segundos...
Cálculo final...
Average_power_consumption= 3.061 +/- 0.168 W
```

The output shows:
- Monitoring duration (50 seconds in this example)
- Average power consumption in Watts
- Standard deviation/uncertainty of the measurement

## Notes

- The script monitors power for a predefined duration (default: 50 seconds)
- The `nohup: ignoring input` message is normal and can be ignored
- Results are automatically saved to `/home/raspi/power_live.log`
- Make sure to replace `RASPI_IP` with your actual Raspberry Pi IP address