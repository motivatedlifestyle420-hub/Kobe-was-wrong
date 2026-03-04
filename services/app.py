from fastapi import FastAPI

app = FastAPI(title="Automation Command Center")

@app.get("/")
def root():
    return {"status": "running"}
