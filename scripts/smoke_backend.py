"""Import/schema and real Uvicorn HTTP smoke check; leaves no server running."""

import importlib
import inspect
import json
import os
import pkgutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import backend
from backend.contracts.base import Contract


def main() -> None:
    models: set[type[Contract]] = set()
    modules = list(pkgutil.walk_packages(backend.__path__, "backend."))
    for info in modules:
        module = importlib.import_module(info.name)
        for _, value in inspect.getmembers(module, inspect.isclass):
            if issubclass(value, Contract):
                models.add(value)
    for model in models:
        model.model_json_schema()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Uvicorn exited before health became ready")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=1
                ) as response:
                    payload = json.load(response)
                assert payload["status"] == "ok"
                print(
                    f"Imported {len(modules)} modules; validated {len(models)} schemas; "
                    "HTTP health OK"
                )
                return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        raise RuntimeError("Uvicorn health timeout")
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


if __name__ == "__main__":
    main()
