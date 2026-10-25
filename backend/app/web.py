"""Serve the compiled Svelte application after all API routes."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_frontend(app: FastAPI, directory: Path | None = None):
    configured = os.environ.get("MARKET_HUNTER_FRONTEND")
    directory = directory or (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    if not (directory / "index.html").is_file():
        if configured:
            raise RuntimeError(f"Frontend compilado não encontrado em {directory}")
        # Normal development uses Vite on its own port.
        return

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def unknown_api(path: str):
        raise HTTPException(404, "Endpoint não encontrado")

    app.mount("/", FrontendFiles(directory=directory, html=True), name="frontend")
