import os
import logging
from dagon import Batch
from dagon.task import Task
from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes.client.rest import ApiException
import time
import json
import uuid

# Reduce Kubernetes logs
logging.getLogger('kubernetes.client.rest').setLevel(logging.WARNING)

class KubernetesTask(Batch):
    """
    Represents a task that runs inside a Kubernetes pod.
    Inherits from Batch to integrate with Dagon's task workflow.
    """

    def __init__(self, name, command, image="ubuntu:20.04", namespace="default",
                 working_dir=None, remove=True, transversal_workflow=None, cleanup_timeout=30):
        """
        Initializes the Kubernetes task.

        Args:
            name (str): Name of the task.
            command (str): Command to execute inside the pod.
            image (str): Container image to use.
            namespace (str): Kubernetes namespace.
            working_dir (str, optional): Working directory for the task.
            remove (bool): If True, removes the pod upon completion.
            transversal_workflow: Transversal workflow if applicable.
        """
        # Initialize the base Dagon task
        Task.__init__(self, name, command, working_dir=working_dir,
                      transversal_workflow=transversal_workflow)

        # Load Kubernetes configuration (from ~/.kube/config)
        config.load_kube_config()

        # API for managing pods
        self.v1 = client.CoreV1Api()

        self.image = image
        self.namespace = namespace
        self.remove = remove
        self.cleanup_timeout = cleanup_timeout

        # Assigned when the pod is created
        self.pod_name = None
        
        # Pod information that Dagon needs for staging
        self.info = None

        # Single execution control
        self.executed = False
        self.execution_result = None

    def create_pod(self):
        """
        Creates a pod in Kubernetes only if it doesn't already exist (avoids duplicates).

        - The pod is kept in 'sleep infinity' state to allow multiple executions.
        """
        if self.pod_name is not None:
            # Pod already exists, reuse it
            print(f"Reusing existing pod: {self.pod_name}")
            return

        # Generate a unique name using UUID and timestamp
        self.pod_name = f"{self.name.lower()}-{uuid.uuid4().hex[:8]}-{int(time.time()*1000)}"

        # Pod definition
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": self.pod_name, "labels": {"app": self.name}},
            "spec": {
                "containers": [{
                    "name": "main",
                    "image": self.image,
                    "command": ["/bin/bash", "-c", "sleep infinity"],
                }],
                "restartPolicy": "Never"
            }
        }

        try:
            self.v1.create_namespaced_pod(namespace=self.namespace, body=pod_manifest)
            print(f"Pod created: {self.pod_name}")
        except Exception as e:
            print(f"Error creating pod {self.pod_name}: {e}")

        # Wait for the pod to be in 'Running' state and get IP
        print(f"Waiting for pod {self.pod_name} to be ready...")
        while True:
            pod = self.v1.read_namespaced_pod(name=self.pod_name, namespace=self.namespace)
            if pod.status.phase == "Running":
                pod_ip = pod.status.pod_ip
                print(f"Pod {self.pod_name} ready with IP: {pod_ip}")
                
                # Configure pod information that Dagon needs
                self.info = {
                    'name': self.name,
                    'ip': pod_ip,
                    'pod_name': self.pod_name,
                    'namespace': self.namespace
                }
                break
            elif pod.status.phase == "Failed":
                raise Exception(f"Pod {self.pod_name} failed: {pod.status.message}")
            time.sleep(0.5)

    def exec_in_pod(self, command):
        """
        Executes a command inside the pod's main container.
        Args:
            command (str): Command to execute.

        Returns:
            str: Output of the executed command.
        """
        # Reduce logging, only show important commands
        if not command.startswith(("mkdir -p", "cat > /tmp")):
            print(f"Executing: {command}")
        resp = stream(self.v1.connect_get_namespaced_pod_exec,
                      self.pod_name,
                      self.namespace,
                      command=["/bin/bash", "-c", command],
                      stderr=True, stdin=False,
                      stdout=True, tty=False,
                      container="main")
        return resp

    def stage_in(self, src_task, src_path, dst_path):
        """
        Copies a file from another pod to this pod so that workflow:/// works.
        This function is called by the Dagon framework.
        """
        # Ensure both pods are created and information is available
        if not hasattr(src_task, 'pod_name') or src_task.pod_name is None:
            src_task.create_pod()
        if self.pod_name is None:
            self.create_pod()
            
        print(f"Copying file {src_path} from {src_task.name} to {self.name}")
        
        try:
            # Read file content in the source pod
            content = src_task.exec_in_pod(f"cat {src_path}")

            # Create destination folder if it doesn't exist
            dst_dir = "/".join(dst_path.split("/")[:-1])
            if dst_dir:
                self.exec_in_pod(f"mkdir -p {dst_dir}")

            # Write content to destination using heredoc to avoid issues with special characters
            escaped_content = content.replace("'", "'\"'\"'")
            self.exec_in_pod(f"cat > {dst_path} << 'EOF'\n{escaped_content}\nEOF")
            print(f"File copied successfully")
        except Exception as e:
            print(f"Error in stage_in: {e}")
            raise

    def remove_pod(self):
        """
        Removes the pod if `remove=True`, similar to `docker run --rm`.
        Protects against non-existent pods.
        """
        if self.remove and self.pod_name is not None:
            pod_to_delete = self.pod_name  # Save reference before cleanup
            try:
                # Method 1: Standard deletion first
                try:
                    self.v1.delete_namespaced_pod(
                        name=pod_to_delete,
                        namespace=self.namespace,
                        body=client.V1DeleteOptions(grace_period_seconds=30)
                    )
                    print(f"Pod {pod_to_delete} deleted")
                except ApiException as e:
                    if e.status == 404:
                        print(f"Pod {pod_to_delete} no longer exists")
                    else:
                        # Method 2: Force immediate deletion if standard method fails
                        print(f"Standard deletion failed, forcing deletion of {pod_to_delete}")
                        self.v1.delete_namespaced_pod(
                            name=pod_to_delete,
                            namespace=self.namespace,
                            body=client.V1DeleteOptions(
                                grace_period_seconds=0,
                                propagation_policy='Background'
                            )
                        )
                        print(f"Pod {pod_to_delete} forcefully deleted")
                        
            except ApiException as e:
                if e.status != 404:
                    print(f"Warning: Could not delete pod {pod_to_delete}: {e.reason}")
                    # Method 3: Last resort - use kubectl if API fails
                    try:
                        import subprocess
                        result = subprocess.run(
                            ['kubectl', 'delete', 'pod', pod_to_delete, '--force', '--grace-period=0'],
                            capture_output=True, text=True, timeout=10
                        )
                        if result.returncode == 0:
                            print(f"Pod {pod_to_delete} deleted using kubectl")
                        else:
                            print(f"kubectl also failed for {pod_to_delete}: {result.stderr}")
                    except Exception as kubectl_error:
                        print(f"kubectl not available to clean up {pod_to_delete}: {kubectl_error}")
            except Exception as e:
                print(f"Unexpected error deleting pod {pod_to_delete}: {e}")
            finally:
                # Clean up references regardless of result
                self.pod_name = None
                self.info = None
    
    def pre_process_command(self, command):
        """
        Override the preprocessing method to intercept workflow:/// URLs
        before Dagon tries to process them.
        """
        # Create the pod if it doesn't exist to ensure we have information available
        if self.pod_name is None:
            self.create_pod()
        
        # Process workflow:/// manually to avoid KeyError
        if "workflow:///" in command:
            import re
            
            # Find all workflow:/// references
            workflow_refs = re.findall(r'workflow:///([^/\s]+)/([^\s]+)', command)
            
            for task_name, file_path in workflow_refs:
                # Search for the referenced task in the workflow
                src_task = None
                if hasattr(self, 'workflow') and self.workflow:
                    for task in self.workflow.tasks:
                        if task.name == task_name:
                            src_task = task
                            break
                
                if src_task:
                    # Ensure the source task has its pod created
                    if not hasattr(src_task, 'pod_name') or src_task.pod_name is None:
                        src_task.create_pod()
                    
                    # Create local temporary file to simulate expected behavior
                    local_path = f"/tmp/{task_name}_{file_path.replace('/', '_')}"
                    
                    try:
                        # Copy file using our stage_in method
                        self.stage_in(src_task, file_path, local_path)
                        
                        # Replace the workflow:// reference with the local path
                        workflow_url = f"workflow:///{task_name}/{file_path}"
                        command = command.replace(workflow_url, local_path)
                    except Exception as e:
                        print(f"Error processing workflow reference {workflow_url}: {e}")
        
        return command

    def on_execute(self, script, script_name):
        """
        Method called when executing the task:

        - Creates the pod if it doesn't exist.
        - Executes the command inside the pod.
        - Returns the result in JSON format, escaping newlines and tabs.
        """
        # Single execution control
        if self.executed:
            print(f"[{self.name}] Returning previous result")
            return self.execution_result

        Task.on_execute(self, script, script_name)

        # Create pod if it doesn't exist
        if self.pod_name is None:
            self.create_pod()

        # Process command to handle workflow:/// references
        processed_command = self.pre_process_command(self.command)

        # Execute command
        result = self.exec_in_pod(processed_command).strip()

        # Escape newlines and tabs
        safe_result = result.replace("\n", "\\n").replace("\t", "\\t")

        # Format output as JSON
        output_json = json.dumps({"result": safe_result})
        print(f"[{self.name}] Output:\n{output_json}")

        # Mark as executed and save result
        self.executed = True
        self.execution_result = {"output": output_json, "code": 0}
        return self.execution_result

    def on_garbage(self):
        """
        Called when cleaning up the task:

        - Removes the pod if applicable.
        """
        self.remove_pod()
        super(KubernetesTask, self).on_garbage()
