"""Run the local web front office and open the room board in a browser."""

from __future__ import annotations

import asyncio
import os
import webbrowser

import uvicorn


async def _serve() -> None:
    host = os.getenv("ARATI_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("ARATI_WEB_PORT", "8000"))
    server = uvicorn.Server(uvicorn.Config("webapp.main:app", host=host, port=port))
    server_task = asyncio.create_task(server.serve())

    while not server.started and not server_task.done():
        await asyncio.sleep(0.1)

    if server_task.done():
        await server_task
        return

    url = f"http://{host}:{port}/rooms"
    print(f"Arati Hotel is ready at {url}. Press Ctrl+C to stop.")
    webbrowser.open(url)
    await server_task


if __name__ == "__main__":
    asyncio.run(_serve())
