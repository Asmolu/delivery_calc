$env:PYTHONPATH="."
uvicorn backend.app.main:app --reload
