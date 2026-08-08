# Copyright (c) 2026 Eric Cooper.
"""Container entry point: `python main.py`.

Reads ``$PORT`` (Cloud Run / Fly / Render / anything that injects it),
binds uvicorn to ``0.0.0.0:$PORT``, and hands off to the FastAPI app.
Defaults to 8000 when ``$PORT`` is unset — matches local dev.

Local dev uses ``uv run uvicorn api.main:app --reload`` directly and
doesn't touch this file. This exists specifically so a container can
``CMD ["python", "main.py"]`` without hardcoding a port.
"""

from __future__ import annotations

import os

import uvicorn

from api.main import app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
