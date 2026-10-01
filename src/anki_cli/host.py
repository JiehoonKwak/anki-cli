from __future__ import annotations

import json
import os
import platform
import socket
from pathlib import Path
from typing import Any

from .backend import AnkiClient


ADDON_ID = "2055492159"


def hostname() -> str:
    return socket.gethostname()


def is_macos() -> bool:
    return platform.system() == "Darwin"


def anki_app_paths() -> list[Path]:
    return [Path("/Applications/Anki.app"), Path.home() / "Applications" / "Anki.app"]


def find_anki_app() -> Path | None:
    for path in anki_app_paths():
        if path.exists():
            return path
    return None


def anki2_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Anki2"


def ankiconnect_addon_dir() -> Path:
    return anki2_dir() / "addons21" / ADDON_ID


def read_ankiconnect_config() -> dict[str, Any] | None:
    addon = ankiconnect_addon_dir()
    for name in ("meta.json", "config.json"):
        path = addon / name
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if name == "meta.json" and isinstance(data, dict) and isinstance(data.get("config"), dict):
                    return data["config"]
                if isinstance(data, dict):
                    return data
            except Exception:
                return None
    return None


def bind_is_local(config: dict[str, Any] | None) -> bool | None:
    if config is None:
        return None
    bind = config.get("webBindAddress", "127.0.0.1")
    return bind in {"127.0.0.1", "localhost", "::1"}


def inspect_host(client: AnkiClient) -> dict[str, Any]:
    config = read_ankiconnect_config()
    reachable = client.reachable()
    return {
        "hostname": hostname(),
        "platform": platform.platform(),
        "is_macos": is_macos(),
        "anki_app": str(find_anki_app()) if find_anki_app() else None,
        "anki_installed": find_anki_app() is not None,
        "ankiconnect_addon": str(ankiconnect_addon_dir()) if ankiconnect_addon_dir().exists() else None,
        "ankiconnect_addon_installed": ankiconnect_addon_dir().exists(),
        "ankiconnect_url": client.url if client.backend == "ankiconnect" else None,
        "collection_path": str(client.path) if client.backend == "headless" else None,
        "ankiconnect_reachable": reachable if client.backend == "ankiconnect" else False,
        "backend": client.backend,
        "collection_reachable": reachable,
        "ankiconnect_bind_local": bind_is_local(config),
        "configured_anki_host": os.environ.get("ANKI_CLI_ANKI_HOST"),
        "looks_like_anki_host": (
            os.environ.get("ANKI_CLI_ANKI_HOST") in {None, "", hostname()}
            and (client.backend == "headless" or find_anki_app() is not None)
        ),
    }
