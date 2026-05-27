#!/usr/bin/env bash
# Start the Trust Layer RAG retrieval API locally.
# PYTHONPATH=. required — all pipeline imports are relative to repo root.
set -e
export PYTHONPATH=.
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
