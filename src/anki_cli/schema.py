from __future__ import annotations

import hashlib
import json
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1
DEFAULT_NOTETYPE = "AnkiCLI-Basic-v1"
DEFAULT_RENDER_MODE = "markdown-safe"
DEFAULT_TAG_POLICY = "merge"
EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
JOB_ID_RE = re.compile(r"^job_[A-Za-z0-9_.-]{8,120}$")
TAG_RE = re.compile(r"^[^\s,]+$")
MEDIA_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
MEDIA_KINDS = {"screenshot", "diagram", "figure", "other"}
MEDIA_TEXT_FIELDS = ("caption", "source_uri", "source_locator", "alt", "selection_reason")


class SchemaError(ValueError):
    """Raised when a queued job does not match the supported schema."""


@dataclass(frozen=True)
class RenderedNote:
    external_id: str
    fields: dict[str, str]
    tags: list[str]
    deck: str
    notetype: str
    tag_policy: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


def new_external_id() -> str:
    return f"acli_{uuid.uuid4().hex}"


def stable_host() -> str:
    return socket.gethostname()


def load_json_object(path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise SchemaError("job file must contain a JSON object")
    return value


def normalize_external_id(value: str | None) -> str:
    external_id = value or new_external_id()
    if not EXTERNAL_ID_RE.match(external_id):
        raise SchemaError(
            "external_id must start with an alphanumeric character and contain "
            "only letters, numbers, underscore, dot, colon, or hyphen"
        )
    return external_id


def normalize_tags(tags: list[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = [part for part in re.split(r"[\s,]+", tags) if part]
    elif isinstance(tags, list) and all(isinstance(tag, str) for tag in tags):
        raw = tags
    else:
        raise SchemaError("tags must be a string or list of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in raw:
        tag = tag.strip()
        if not tag:
            continue
        if not TAG_RE.match(tag):
            raise SchemaError(f"invalid tag: {tag!r}")
        if tag not in seen:
            normalized.append(tag)
            seen.add(tag)
    return normalized


def _media_filename(path: Path) -> str:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:12]
    stem = MEDIA_FILENAME_RE.sub("_", path.stem).strip("._") or "media"
    suffix = MEDIA_FILENAME_RE.sub("", path.suffix.lower())
    return f"anki_cli_{digest}_{stem}{suffix}"


def _normalize_media_kind(value: Any) -> str:
    kind = "other" if value is None else value
    if not isinstance(kind, str) or kind not in MEDIA_KINDS:
        raise SchemaError(f"note.media.kind must be one of {sorted(MEDIA_KINDS)}")
    return kind


def _normalize_optional_media_text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaError(f"note.media.{key} must be a string")
    return value


def normalize_media_item(item: dict[str, Any], *, default_field: str | None = None) -> dict[str, str]:
    if not isinstance(item, dict):
        raise SchemaError("media entries must be objects")
    field = item.get("field", default_field)
    if field not in {"front", "back"}:
        raise SchemaError("note.media field must be 'front' or 'back'")
    path_value = item.get("path") or item.get("file")
    if not isinstance(path_value, str) or not path_value:
        raise SchemaError("note.media.path is required")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise SchemaError(f"media file does not exist: {path_value}")
    data = path.read_bytes()
    normalized = {
        "field": field,
        "path": str(path),
        "filename": _media_filename(path),
        "original_name": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "kind": _normalize_media_kind(item.get("kind")),
    }
    for key in MEDIA_TEXT_FIELDS:
        value = _normalize_optional_media_text(item, key)
        if value is not None:
            normalized[key] = value
    return normalized


def normalize_media_files(files: list[str] | None, *, field: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for file_value in files or []:
        normalized.append(normalize_media_item({"path": file_value, "kind": "other"}, default_field=field))
    return normalized


def normalize_media_items(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    return [normalize_media_item(item) for item in items or []]


def build_upsert_job(
    *,
    deck: str,
    front: str,
    back: str,
    external_id: str | None = None,
    extra: str = "",
    source_title: str = "",
    source_uri: str = "",
    source_locator: str = "",
    source_hash: str = "",
    tags: list[str] | str | None = None,
    render_mode: str = DEFAULT_RENDER_MODE,
    metadata: dict[str, Any] | None = None,
    notetype: str = DEFAULT_NOTETYPE,
    agent: str = "unknown",
    front_media_files: list[str] | None = None,
    back_media_files: list[str] | None = None,
    media_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not deck.strip():
        raise SchemaError("deck is required")
    if not front.strip():
        raise SchemaError("front is required")
    if not back.strip():
        raise SchemaError("back is required")
    if render_mode not in {"plain", "markdown-safe", "html"}:
        raise SchemaError(f"unsupported render_mode: {render_mode}")
    if metadata is not None:
        try:
            json.dumps(metadata)
        except TypeError as exc:
            raise SchemaError("metadata must be JSON-serializable") from exc
    media = normalize_media_files(front_media_files, field="front") + normalize_media_files(
        back_media_files, field="back"
    ) + normalize_media_items(media_items)

    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "job_id": new_job_id(),
        "operation": "upsert_note",
        "created_at": now_iso(),
        "created_by": {
            "agent": agent,
            "host": stable_host(),
        },
        "target": {
            "deck": deck.strip(),
            "notetype": notetype,
        },
        "note": {
            "external_id": normalize_external_id(external_id),
            "front": front,
            "back": back,
            "extra": extra,
            "source_title": source_title,
            "source_uri": source_uri,
            "source_locator": source_locator,
            "source_hash": source_hash,
            "tags": normalize_tags(tags),
            "render_mode": render_mode,
            "tag_policy": DEFAULT_TAG_POLICY,
            "metadata": metadata or {},
            "media": media,
        },
    }


def validate_job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise SchemaError(f"unsupported schema_version: {job.get('schema_version')!r}")
    job_id = job.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        raise SchemaError("job_id is missing or not filename-safe")
    if job.get("operation") != "upsert_note":
        raise SchemaError(f"unsupported operation: {job.get('operation')!r}")
    target = job.get("target")
    note = job.get("note")
    if not isinstance(target, dict):
        raise SchemaError("target must be an object")
    if not isinstance(note, dict):
        raise SchemaError("note must be an object")
    deck = target.get("deck")
    notetype = target.get("notetype", DEFAULT_NOTETYPE)
    if not isinstance(deck, str) or not deck.strip():
        raise SchemaError("target.deck is required")
    if not isinstance(notetype, str) or not notetype.strip():
        raise SchemaError("target.notetype is required")
    for key in ("front", "back"):
        if not isinstance(note.get(key), str) or not note[key].strip():
            raise SchemaError(f"note.{key} is required")
    note["external_id"] = normalize_external_id(note.get("external_id"))
    note["tags"] = normalize_tags(note.get("tags"))
    render_mode = note.get("render_mode", DEFAULT_RENDER_MODE)
    if render_mode not in {"plain", "markdown-safe", "html"}:
        raise SchemaError(f"unsupported render_mode: {render_mode}")
    metadata = note.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SchemaError("note.metadata must be an object")
    try:
        json.dumps(metadata)
    except TypeError as exc:
        raise SchemaError("note.metadata must be JSON-serializable") from exc
    media = note.get("media", [])
    if not isinstance(media, list):
        raise SchemaError("note.media must be a list")
    for item in media:
        if not isinstance(item, dict):
            raise SchemaError("note.media entries must be objects")
        if item.get("field") not in {"front", "back"}:
            raise SchemaError("note.media field must be 'front' or 'back'")
        for key in ("path", "filename", "original_name", "sha256"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise SchemaError(f"note.media.{key} is required")
        item["kind"] = _normalize_media_kind(item.get("kind"))
        for key in MEDIA_TEXT_FIELDS:
            value = _normalize_optional_media_text(item, key)
            if value is not None:
                item[key] = value
    return job
