from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .schema import now_iso


STATE_DIR = Path("state")
PENDING_DIR = STATE_DIR / "queue" / "pending"
DONE_DIR = STATE_DIR / "queue" / "done"
FAILED_DIR = STATE_DIR / "queue" / "failed"
LEDGER_DIR = STATE_DIR / "ledger"
LEDGER_PATH = LEDGER_DIR / "notes.jsonl"


def ensure_state_dirs(root: Path) -> None:
    for rel in (PENDING_DIR, DONE_DIR, FAILED_DIR, LEDGER_DIR):
        (root / rel).mkdir(parents=True, exist_ok=True)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def job_hash(job: dict[str, Any]) -> str:
    encoded = json.dumps(job, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def pending_jobs(root: Path) -> list[Path]:
    ensure_state_dirs(root)
    return sorted((root / PENDING_DIR).glob("*.json"))


def enqueue_job(root: Path, job: dict[str, Any]) -> Path:
    ensure_state_dirs(root)
    job_id = job["job_id"]
    path = root / PENDING_DIR / f"{job_id}.json"
    if path.exists():
        raise FileExistsError(f"pending job already exists: {path}")
    write_json_atomic(path, job)
    return path


def mark_done(root: Path, pending_path: Path, job: dict[str, Any], result: dict[str, Any]) -> Path:
    payload = {
        "job": job,
        "result": {
            **result,
            "status": "done",
            "timestamp": now_iso(),
            "job_hash": job_hash(job),
        },
    }
    dest = root / DONE_DIR / pending_path.name
    write_json_atomic(dest, payload)
    pending_path.unlink(missing_ok=True)
    return dest


def mark_failed(
    root: Path,
    pending_path: Path,
    job: dict[str, Any] | None,
    *,
    error: str,
    error_kind: str,
    host: str,
    anki_status: dict[str, Any],
) -> Path:
    previous_attempts = 0
    if pending_path.exists():
        try:
            existing = read_json(pending_path)
            previous_attempts = int(existing.get("result", {}).get("attempt_count", 0))
        except Exception:
            previous_attempts = 0
    payload = {
        "job": job,
        "result": {
            "status": "failed",
            "attempt_count": previous_attempts + 1,
            "last_error": error,
            "last_error_kind": error_kind,
            "host": host,
            "timestamp": now_iso(),
            "anki_status": anki_status,
            "job_hash": job_hash(job) if job is not None else None,
        },
    }
    dest = root / FAILED_DIR / pending_path.name
    write_json_atomic(dest, payload)
    pending_path.unlink(missing_ok=True)
    return dest


def append_ledger(root: Path, entry: dict[str, Any]) -> None:
    ensure_state_dirs(root)
    path = root / LEDGER_PATH
    with open(path, "a", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def read_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / LEDGER_PATH
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                entries.append(value)
    return entries


def git_available(root: Path) -> bool:
    return (root / ".git").exists()


def git_status_short(root: Path) -> str:
    if not git_available(root):
        return "not a git repository"
    proc = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.stdout.strip()


def maybe_git_commit(root: Path, message: str, push: bool = False) -> None:
    if not git_available(root):
        return
    subprocess.run(["git", "add", "state"], cwd=root, check=True)
    status = git_status_short(root)
    if status:
        subprocess.run(["git", "commit", "-m", message], cwd=root, check=True)
    if push:
        subprocess.run(["git", "push"], cwd=root, check=True)


def repo_root_from_cwd() -> Path:
    return Path.cwd()


def clear_state(root: Path) -> None:
    shutil.rmtree(root / STATE_DIR, ignore_errors=True)
