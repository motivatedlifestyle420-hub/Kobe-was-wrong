import pathlib

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

_INDEX_PATH = pathlib.Path(__file__).parent.parent / "Index.html"
_INDEX_HTML = _INDEX_PATH.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX_HTML
