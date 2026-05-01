"""FastAPI entrypoint."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import router as api_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="VitalSense",
    description="Real-time health monitoring + automated emergency response.",
    version="0.1.0",
)

app.include_router(api_router)

# Static + templates for the dashboard
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}
