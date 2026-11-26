"""
Entrypoint module for Railway / Nixpacks default ASGI command (`uvicorn main:app`).
Re-exports `app` from `app.py`.
"""

from app import app

__all__ = ["app"]
