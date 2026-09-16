"""
Discloud entry point for Thread Discord Gateway Worker.
Runs the standalone gateway worker process via python main.py or python -m app.channels.run_gateway.
Does NOT start Uvicorn or FastAPI.
"""
import asyncio
import os
import sys

# Ensure package root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.channels.run_gateway import main

if __name__ == "__main__":
    asyncio.run(main())
