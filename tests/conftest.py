import os
import socket
import threading
import time

import pytest
import uvicorn

# On GitHub Actions, Typer forces colors and boxes in error messages, which breaks the text checks.
# Set before Typer is imported by the test modules.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def start_server():
    """Return a function that runs a FastAPI app in a thread and gives back its URL."""
    servers = []

    def start(app):
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        servers.append((server, thread))
        while not server.started:
            time.sleep(0.02)
        return f"http://127.0.0.1:{port}"

    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join()
