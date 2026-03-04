from fastapi import FastAPI

from services.kernel import kernel

app = FastAPI(title="Automation Command Center")


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/kernel/tasks")
def list_tasks():
    return {"tasks": kernel.task_names()}


@app.post("/kernel/run/{task_name}")
def run_task(task_name: str):
    result = kernel.run(task_name)
    return {
        "task_name": result.task_name,
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "ran_at": result.ran_at,
    }
