# AI Test Platform Backend

FastAPI + Playwright + SQLite

## Setup
pip install -e ".[dev]"
playwright install chromium

## Run
uvicorn backend.main:app --reload
