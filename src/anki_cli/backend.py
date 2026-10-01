"""Own a headless collection session without any GUI or HTTP backend."""

from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from typing import Iterator

from .headless import HeadlessClient, collection_target

AnkiClient = HeadlessClient

_scope: ContextVar[ExitStack | None] = ContextVar("anki_cli_scope", default=None)


@contextmanager
def client_scope() -> Iterator[None]:
    with ExitStack() as stack:
        token = _scope.set(stack)
        try:
            yield
        finally:
            _scope.reset(token)


def get_client(*, timeout: float | None = None) -> AnkiClient:
    if os.environ.get("ANKI_CLI_BACKEND", "headless") != "headless":
        raise ValueError(
            "only headless is supported; remove the legacy ANKI_CLI_BACKEND setting"
        )
    path, profile = collection_target()
    if timeout is not None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        profile = {**profile, "networkTimeout": max(1, int(timeout))}
    client = HeadlessClient(path, profile)
    stack = _scope.get()
    if stack is None:
        client.close()
        raise RuntimeError("headless client requires a client_scope")
    stack.callback(client.close)
    return client
