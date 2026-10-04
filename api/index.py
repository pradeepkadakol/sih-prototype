"""Vercel's ASGI entry point for the existing FastAPI application."""

from backend.app.main import create_app

app = create_app()
