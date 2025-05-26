import json
import os.path
import time

from dagon import Workflow
from dagon.task import DagonTask, TaskType

# Check if this is the main
if __name__ == '__main__':
    # Create the orchestration workflow
    workflow = Workflow("DataFlow-Demo-Docker")

    # The task a
    taskA = DagonTask(TaskType.DOCKER, "A", "mkdir output;hostname > output/f1.txt", image="ubuntu:20.04")

    # The task b
    taskB = DagonTask(TaskType.DOCKER, "B", "echo $RANDOM > f2.txt; cat workflow:///A/output/f1.txt >> f2.txt", image="python:3.9")

    # The task c
    taskC = DagonTask(TaskType.DOCKER, "C", "echo $RANDOM > f2.txt; cat workflow:///A/output/f1.txt >> f2.txt", image="python:3.9")

    # The task d
    taskD = DagonTask(TaskType.DOCKER, "D", "cat workflow:///B/f2.txt >> f3.txt; cat workflow:///C/f2.txt >> f3.txt", image="centos:8")

    # add tasks to the workflow
    workflow.add_task(taskA)
    workflow.add_task(taskB)
    workflow.add_task(taskC)
    workflow.add_task(taskD)

    workflow.make_dependencies()

    jsonWorkflow = workflow.as_json()
    with open('dataflow-demo-docker.json', 'w') as outfile:
        stringWorkflow = json.dumps(jsonWorkflow, sort_keys=True, indent=2)
        outfile.write(stringWorkflow)

    # run the workflow
    workflow.run()

    if workflow.get_dry() is False:
        # set the result filename
        result_filename = taskD.get_scratch_dir() + "/f3.txt"
        while not os.path.exists(result_filename):
            time.sleep(1)

        # get the results
        with open(result_filename, "r") as infile:
            result = infile.readlines()
            print(result)
