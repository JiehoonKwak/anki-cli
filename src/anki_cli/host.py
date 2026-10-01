from __future__ import annotations

import os
import platform
import socket
from typing import Any

from .backend import AnkiClient


def hostname() -> str:
    return socket.gethostname()


def inspect_host(client: AnkiClient) -> dict[str, Any]:
    return {
        "hostname": hostname(),
        "platform": platform.platform(),
        "backend": "headless",
        "collection_path": str(client.path),
        "collection_reachable": client.reachable(),
        "configured_anki_host": os.environ.get("ANKI_CLI_ANKI_HOST"),
    }
