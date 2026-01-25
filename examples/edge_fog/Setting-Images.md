# Dockerizing DHT Workflow for Raspberry Pi

This guide walks you through creating a Dockerfile, building a local Docker image, and updating your workflow script to use the containerized environment.

## 1. Create the Dockerfile

Create a file named `Dockerfile` in your project folder with the following content to bundle all dependencies:

```dockerfile
FROM python:3.9-slim
RUN pip install --no-cache-dir pyserial pandas pymongo
```

## 2. Build the Local Image

Run this command in your Raspberry Pi terminal to build the image once:

```bash
docker build -t dht-workflow-local:latest .
```

## 3. Update the Workflow

Update your `edge_fog_cloud_docker_metrics.py` to use `image="dht-workflow-local:latest"` and remove all `pip install` lines from the task commands.

Ensure that your script is configured to pull and run the containerized environment without installing dependencies at runtime. This will streamline your deployment on the Raspberry Pi.
