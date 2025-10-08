## Apptainer Tasks with DagOnStar

DagOnStar supports the deployment of tasks on HPC environments using [Apptainer](https://apptainer.org/) containers.

## Requirements

* [Apptainer](https://apptainer.org/) (container runtime for HPC)
* Python 3.8+
* Virtualenv

## Installation

Clone the repository and prepare the Python environment:

```bash
git clone https://github.com/CoCo-ARCOS/dagonstar-containers.git
cd dagonstar-containers/

virtualenv venv
. venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$PWD:$PYTHONPATH
```

Copy the configuration file:

```bash
cp dagon.ini.sample examples/dataflow/apptainer/dagon.ini
```

Set up Apptainer automatically with the provided script:

```bash
bash dagon/setup-apptainer.sh
```

This will:

- Install Apptainer
- Configure cache and temporary directories  
- Set environment variables permanently
- Test basic functionality

> [!NOTE]
> You only need to run this setup once.

## Running Apptainer tasks

Navigate to the Apptainer example and run the demo:

```bash
cd examples/dataflow/apptainer/
python dataflow-demo-apptainer.py
```

During the execution, the demo will create containers for each task, execute the commands with overlays for file sharing, and finally clean up temporary files (if you specify `remove=True`).


## Remote Apptainer Tasks with DagOnStar

DagOnStar allows you to execute Apptainer tasks on remote servers via SSH. This is useful for distributing workloads across multiple machines or accessing HPC resources remotely.

## Prerequisites

Before running remote tasks, ensure the following:

1. Apptainer is installed on the remote machine
2. SSH service is enabled on the remote machine

## Remote Machine Setup

### Installing Apptainer

On the remote machine (e.g., your Kali VM or HPC node), install and configure Apptainer:

```bash
# On the remote machine (e.g., Kali VM)
sudo apt update
sudo apt install -y apptainer
```

### Configuring SSH Service

Enable and verify SSH service:

```bash
# Enable SSH service to start on boot
sudo systemctl enable ssh

# Start SSH service
sudo systemctl start ssh

# Verify SSH is running
sudo systemctl status ssh

# Check your IP address and note it down
ip a
```

> [!TIP]
> Look for the `inet` address under your network interface (usually `eth0` or `wlan0`). This is the IP you'll use in the configuration.

## Configuration

Before running remote examples, edit the `dagon.ini` file in your example directory and configure the SSH parameters:

```ini
[ssh]
# SSH Configuration for Remote Tasks
# Edit these values according to your environment
remote_ip = 192.168.1.100    # IP address of the remote server (from 'ip a' command)
ssh_user = your_username      # Your SSH username on the remote machine
ssh_port = 22                 # SSH port (default 22, use 2222 if using Docker SSH)
```

### Configuration Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `remote_ip` | IP address or hostname of the remote server | `192.168.1.100`, `10.0.0.5`, or `hpc.example.com` |
| `ssh_user` | SSH username for authentication | `kali`, `ubuntu`, `your_username` |
| `ssh_port` | SSH port number | `22` (standard), `2222` (Docker), or custom port |

## Running Remote Examples

Once configured, navigate to the remote Apptainer example and run:

```bash
cd examples/dataflow/apptainer/
python taskflow.py
```

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]

## Support

[Add support information here]