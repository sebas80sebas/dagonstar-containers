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
cp dagon.ini.sample examples/taskflow/dagon.ini
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
python taskflow-demo-apptainer.py
```

During the execution, the demo will create containers for each task, execute the commands with overlays for file sharing, and finally clean up temporary files (if you specify `remove=True`).

## Configuration Options

### Basic Usage
```python
from dagon.task import DagonTask, TaskType

# Simple task with Docker Hub image
task = DagonTask(TaskType.APPTAINER, "task1", 
                 "echo Hello HPC", 
                 image="docker://ubuntu:20.04")
```

### Advanced Configuration
```python
# Task with bind mounts for HPC storage
task = DagonTask(TaskType.APPTAINER, "analysis", 
                 "python analyze.py /data/input.csv", 
                 image="docker://python:3.9",
                 bind_paths=["/scratch:/scratch", "/shared:/shared"],
                 overlay_size="1024")  # 1GB overlay

# Using pre-built SIF image
task = DagonTask(TaskType.APPTAINER, "simulation", 
                 "./run_simulation", 
                 image="/apps/containers/simulation.sif")
```
