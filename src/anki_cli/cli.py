from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .backend import AnkiClient, client_scope, get_client
from .gap import build_gap_export
from .host import hostname, inspect_host
from .queue import (
    DONE_DIR,
    FAILED_DIR,
    LEDGER_PATH,
    PENDING_DIR,
    append_ledger,
    enqueue_job,
    ensure_state_dirs,
    mark_done,
    mark_failed,
    pending_jobs,
    read_json,
    read_ledger,
)
from .card import ensure_notetype, render_preview_html, rendered_fields
from .schema import DEFAULT_NOTETYPE, SchemaError, build_upsert_job, now_iso, validate_job


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))


def default_state_root() -> Path:
    configured = Path(os.environ.get("XDG_STATE_HOME") or "").expanduser()
    base = configured if configured.is_absolute() else Path.home() / ".local" / "state"
    return base / "anki-cli"


def read_text_arg(value: str | None, file_value: str | None, *, name: str, required: bool = False) -> str:
    if value is not None and file_value is not None:
        raise SystemExit(f"--{name} and --{name}-file are mutually exclusive")
    if file_value is not None:
        return Path(file_value).read_text(encoding="utf-8")
    if value is not None:
        return value
    if required:
        raise SystemExit(f"--{name} or --{name}-file is required")
    return ""


def parse_metadata(value: str | None, file_value: str | None) -> dict[str, Any]:
    if value is not None and file_value is not None:
        raise SystemExit("--metadata-json and --metadata-file are mutually exclusive")
    if file_value is not None:
        raw = Path(file_value).read_text(encoding="utf-8")
    elif value is not None:
        raw = value
    else:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit("metadata must be a JSON object")
    return parsed


def parse_media_manifests(file_values: list[str] | None) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    for file_value in file_values or []:
        parsed = json.loads(Path(file_value).read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            parsed_media = parsed.get("media")
        else:
            parsed_media = parsed
        if not isinstance(parsed_media, list):
            raise SystemExit("media manifest must be a list or an object with a media list")
        for item in parsed_media:
            if not isinstance(item, dict):
                raise SystemExit("media manifest entries must be objects")
            media.append(item)
    return media


def anki_status(client: AnkiClient) -> dict[str, Any]:
    try:
        return {"reachable": True, "backend": client.backend, "version": client.version(), "url": client.url}
    except Exception as exc:
        return {"reachable": False, "error": str(exc), "url": client.url}


def ensure_deck(client: AnkiClient, deck: str) -> None:
    if deck not in client.deck_names():
        client.create_deck(deck)


SCHEDULING_KEYS = ["cardId", "note", "ord", "type", "queue", "due", "interval", "reps", "lapses"]


def core_card_state(info: dict[str, Any]) -> dict[str, Any]:
    return {key: info.get(key) for key in SCHEDULING_KEYS}


def move_cards_to_deck(
    client: AnkiClient,
    cards: list[int],
    deck: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    before = client.cards_info(cards) if cards else []
    before_by_id = {int(info["cardId"]): info for info in before}
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "target_deck": deck,
            "count": len(cards),
            "card_ids": cards,
            "current_decks": sorted({info.get("deckName", "") for info in before}),
        }
    ensure_deck(client, deck)
    if cards:
        client.change_deck(cards, deck)
    after = client.cards_info(cards) if cards else []
    errors: list[str] = []
    for info in after:
        card_id = int(info["cardId"])
        if info.get("deckName") != deck:
            errors.append(f"card {card_id}: deck {info.get('deckName')!r} != {deck!r}")
        if core_card_state(before_by_id[card_id]) != core_card_state(info):
            errors.append(f"card {card_id}: scheduling changed")
    return {
        "ok": not errors,
        "dry_run": False,
        "target_deck": deck,
        "count": len(cards),
        "card_ids": cards,
        "preserved_scheduling": not errors,
        "errors": errors,
    }


def ensure_note_cards_in_deck(
    client: AnkiClient,
    note_id: int,
    deck: str,
) -> dict[str, Any]:
    infos = client.notes_info(notes=[note_id])
    if not infos:
        raise RuntimeError(f"note {note_id} not found after upsert")
    cards = [int(card_id) for card_id in infos[0].get("cards", [])]
    current = client.cards_info(cards) if cards else []
    current_decks = sorted({info.get("deckName", "") for info in current})
    if current_decks == [deck]:
        return {
            "ok": True,
            "status": "already_in_target",
            "target_deck": deck,
            "count": len(cards),
            "card_ids": cards,
            "current_decks": current_decks,
        }
    result = move_cards_to_deck(client, cards, deck)
    result["status"] = "moved"
    result["current_decks_before_move"] = current_decks
    return result


def note_field(info: dict[str, Any], field: str) -> str:
    fields = info.get("fields", {})
    value = fields.get(field, {})
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return ""


def find_note_by_external_id(client: AnkiClient, notetype: str, external_id: str) -> dict[str, Any] | None:
    infos = client.notes_info(query=f"note:{notetype}")
    matches = [info for info in infos if note_field(info, "ExternalID") == external_id]
    if len(matches) > 1:
        raise RuntimeError(f"multiple notes found for ExternalID {external_id!r}: {[m.get('noteId') for m in matches]}")
    return matches[0] if matches else None


def upsert_job(client: AnkiClient, job: dict[str, Any]) -> dict[str, Any]:
    target = job["target"]
    note = job["note"]
    deck = target["deck"]
    notetype = target.get("notetype", DEFAULT_NOTETYPE)
    ensure_deck(client, deck)
    ensure_notetype(client, notetype)
    fields = rendered_fields(job)
    for media in note.get("media", []):
        client.store_media_file(media["filename"], media["path"])
    existing = find_note_by_external_id(client, notetype, note["external_id"])
    tags = list(note.get("tags", []))
    if existing is None:
        note_id = client.add_note(deck, notetype, fields, tags)
        deck_move = ensure_note_cards_in_deck(client, note_id, deck)
        return {"action": "added", "note_id": note_id, "deck": deck, "notetype": notetype, "deck_move": deck_move}

    note_id = int(existing["noteId"])
    if note.get("tag_policy", "merge") == "merge":
        existing_tags = existing.get("tags", [])
        tags = sorted({*existing_tags, *tags})
    client.update_note(note_id, fields, tags)
    deck_move = ensure_note_cards_in_deck(client, note_id, deck)
    return {
        "action": "updated",
        "note_id": note_id,
        "deck": deck,
        "notetype": notetype,
        "deck_move": deck_move,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    client = get_client()
    report = inspect_host(client)
    report.update(
        {
            "root": str(root),
            "queue_dirs": {
                "pending": str(root / PENDING_DIR),
                "done": str(root / DONE_DIR),
                "failed": str(root / FAILED_DIR),
                "ledger": str(root / LEDGER_PATH),
            },
        }
    )
    print_json(report)
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    client = get_client(timeout=args.timeout)
    status = anki_status(client)
    print_json({"ok": status["reachable"], "message": "collection ready; no desktop launch", "status": status})
    return 0 if status["reachable"] else 1


def cmd_enqueue_upsert(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    front = read_text_arg(args.front, args.front_file, name="front", required=True)
    back = read_text_arg(args.back, args.back_file, name="back", required=True)
    extra = read_text_arg(args.extra, args.extra_file, name="extra")
    metadata = parse_metadata(args.metadata_json, args.metadata_file)
    media_items = parse_media_manifests(args.media_manifest)
    job = build_upsert_job(
        deck=args.deck,
        front=front,
        back=back,
        external_id=args.external_id,
        extra=extra,
        source_title=args.source_title or "",
        source_uri=args.source_uri or "",
        source_locator=args.source_locator or "",
        source_hash=args.source_hash or "",
        tags=args.tags or [],
        render_mode=args.render_mode,
        metadata=metadata,
        notetype=args.notetype,
        agent=args.agent,
        front_media_files=args.front_media_file or [],
        back_media_files=args.back_media_file or [],
        media_items=media_items,
    )
    if args.preview_html:
        Path(args.preview_html).write_text(render_preview_html(job), encoding="utf-8")
    if args.no_enqueue:
        print_json(
            {
                "ok": True,
                "preview_html": str(Path(args.preview_html).resolve()) if args.preview_html else None,
                "job_id": job["job_id"],
                "external_id": job["note"]["external_id"],
                "enqueued": False,
            }
        )
        return 0
    path = enqueue_job(root, job)
    print_json({"ok": True, "path": str(path), "job_id": job["job_id"], "external_id": job["note"]["external_id"]})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_state_dirs(root)
    pending = sorted((root / PENDING_DIR).glob("*.json"))
    done = sorted((root / DONE_DIR).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    failed = sorted((root / FAILED_DIR).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    report = {
        "root": str(root),
        "pending_count": len(pending),
        "done_count": len(done),
        "failed_count": len(failed),
        "recent_done": [p.name for p in done[: args.limit]],
        "recent_failed": [p.name for p in failed[: args.limit]],
    }
    print_json(report)
    return 0


def cmd_decks(args: argparse.Namespace) -> int:
    client = get_client()
    decks = client.deck_names()
    items: list[dict[str, Any]] = []
    for deck in decks:
        item: dict[str, Any] = {"name": deck}
        if args.counts:
            cards = client.find_cards(f'deck:"{deck}"')
            infos = client.cards_info(cards)
            item["card_count"] = sum(1 for info in infos if info.get("deckName") == deck)
        items.append(item)
    print_json({"ok": True, "count": len(items), "items": items})
    return 0


def cmd_move_deck(args: argparse.Namespace) -> int:
    client = get_client()
    if args.sync_first:
        client.sync()
    query = f'deck:"{args.from_deck}"'
    if args.query:
        query = f"{query} {args.query}"
    cards = client.find_cards(query)
    result = move_cards_to_deck(client, cards, args.to_deck, dry_run=args.dry_run)
    result.update({"query": query, "from_deck": args.from_deck})
    sync_result = None
    if args.sync and not args.dry_run and result["ok"]:
        sync_result = client.sync()
    result["sync"] = sync_result
    print_json(result)
    return 0 if result["ok"] else 1


def cmd_drain(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ensure_state_dirs(root)
    client = None if args.dry_run else get_client(timeout=args.timeout)
    if not args.dry_run and not client.reachable():
        print_json({"ok": False, "error": "collection unavailable; desktop launch disabled", "status": anki_status(client)})
        return 1

    processed: list[dict[str, Any]] = []
    failures = 0
    jobs = pending_jobs(root)
    if args.limit is not None:
        jobs = jobs[: args.limit]
    for path in jobs:
        job: dict[str, Any] | None = None
        try:
            job = validate_job(read_json(path))
            fields = rendered_fields(job)
            if args.dry_run:
                processed.append(
                    {
                        "job_id": job["job_id"],
                        "external_id": job["note"]["external_id"],
                        "path": str(path),
                        "dry_run": True,
                        "rendered_fields": sorted(fields),
                    }
                )
                continue
            result = upsert_job(client, job)
            result.update({"job_id": job["job_id"], "external_id": job["note"]["external_id"], "host": hostname()})
            mark_done(root, path, job, result)
            append_ledger(
                root,
                {
                    "external_id": job["note"]["external_id"],
                    "note_id": result["note_id"],
                    "deck": job["target"]["deck"],
                    "notetype": job["target"].get("notetype", DEFAULT_NOTETYPE),
                    "job_id": job["job_id"],
                    "updated_at": now_iso(),
                    "source_hash": job["note"].get("source_hash", ""),
                    "action": result["action"],
                },
            )
            processed.append(result)
        except SchemaError as exc:
            failures += 1
            if args.dry_run:
                processed.append({"path": str(path), "dry_run": True, "error": str(exc), "error_kind": "schema_error"})
            else:
                dest = mark_failed(
                    root,
                    path,
                    job,
                    error=str(exc),
                    error_kind="schema_error",
                    host=hostname(),
                    anki_status=anki_status(client),
                )
                processed.append({"path": str(path), "failed": str(dest), "error": str(exc), "error_kind": "schema_error"})
        except Exception as exc:
            failures += 1
            if args.dry_run:
                processed.append({"path": str(path), "dry_run": True, "error": str(exc), "error_kind": "backend_error"})
            else:
                dest = mark_failed(
                    root,
                    path,
                    job,
                    error=str(exc),
                    error_kind="backend_error",
                    host=hostname(),
                    anki_status=anki_status(client),
                )
                processed.append({"path": str(path), "failed": str(dest), "error": str(exc), "error_kind": "backend_error"})

    sync_result: dict[str, Any] | None = None
    if args.sync and not args.dry_run and processed and failures == 0:
        try:
            sync_result = {"ok": True, "result": client.sync()}
        except Exception as exc:
            sync_result = {"ok": False, "error": str(exc)}

    print_json({"ok": failures == 0, "backend": client.backend if client else None, "dry_run": args.dry_run, "processed": processed, "sync": sync_result})
    return 0 if failures == 0 else 1


def cmd_find(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.ledger:
        entries = read_ledger(root)
        if args.external_id:
            entries = [entry for entry in entries if entry.get("external_id") == args.external_id]
        if args.deck:
            entries = [entry for entry in entries if entry.get("deck") == args.deck]
        print_json({"mode": "ledger", "count": len(entries), "items": entries})
        return 0
    client = get_client()
    if args.sync_first:
        client.sync()
    if args.external_id:
        info = find_note_by_external_id(client, args.notetype or DEFAULT_NOTETYPE, args.external_id)
        print_json({"mode": "live", "count": 1 if info else 0, "items": [info] if info else []})
        return 0
    query_parts = []
    if args.notetype:
        query_parts.append(f"note:{args.notetype}")
    if args.deck:
        query_parts.append(f'deck:"{args.deck}"')
    for tag in args.tag or []:
        query_parts.append(f"tag:{tag}")
    if args.marked:
        query_parts.append("tag:marked")
    if args.flag is not None:
        query_parts.append(f"flag:{args.flag}")
    infos = client.notes_info(query=" ".join(query_parts))
    print_json({"mode": "live", "count": len(infos), "items": infos})
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    client = get_client()
    if args.sync_first:
        client.sync()
    query_parts: list[str] = []
    if args.external_id:
        info = find_note_by_external_id(client, args.notetype or DEFAULT_NOTETYPE, args.external_id)
        infos = [info] if info else []
    else:
        query_parts = []
        if args.notetype:
            query_parts.append(f"note:{args.notetype}")
        if args.deck:
            query_parts.append(f'deck:"{args.deck}"')
        for tag in args.tag or []:
            query_parts.append(f"tag:{tag}")
        if args.marked:
            query_parts.append("tag:marked")
        if args.flag is not None:
            query_parts.append(f"flag:{args.flag}")
        infos = client.notes_info(query=" ".join(query_parts))

    card_ids: list[int] = []
    if args.flag is not None:
        if args.external_id:
            candidate_ids = [int(cid) for info in infos for cid in info.get("cards", [])]
            card_ids = [int(info["cardId"]) for info in client.cards_info(candidate_ids) if int(info.get("flags", 0)) & 7 == args.flag]
        else:
            card_ids = client.find_cards(" ".join(query_parts))
    note_ids = [int(info["noteId"]) for info in infos]
    removed_tags: list[str] = []
    if args.marked:
        removed_tags.append("marked")
    if args.remove_tag:
        removed_tags.extend(args.remove_tag)
    if note_ids and removed_tags and not args.dry_run:
        client.remove_tags(note_ids, removed_tags)
    flag_result = None
    if card_ids and args.flag is not None and not args.dry_run:
        flag_result = client.set_card_flag(card_ids, 0)
    sync_result = None
    if args.sync and not args.dry_run:
        sync_result = client.sync()
    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "matched_count": len(note_ids),
            "note_ids": note_ids,
            "card_ids": card_ids,
            "removed_tags": removed_tags,
            "cleared_flag": args.flag,
            "flag_result": flag_result,
            "sync": sync_result,
        }
    )
    return 0


def cmd_gap_export(args: argparse.Namespace) -> int:
    client = get_client()
    if args.sync_first:
        client.sync()
    export = build_gap_export(
        client,
        days=args.days,
        recent_days=args.recent_days,
        limit=args.limit,
        max_pool=args.max_pool,
        include_text=args.include_text,
        max_field_chars=args.max_field_chars,
        min_reps=args.min_reps,
        min_interval=args.min_interval,
        decks=args.deck or None,
        extra_query=args.query,
    )
    print_json(export)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    client = get_client()
    result = client.sync()
    print_json({"ok": True, "result": result})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anki-cli")
    parser.add_argument(
        "--root",
        default=default_state_root(),
        help=(
            "Directory containing state/ (default: "
            "$XDG_STATE_HOME/anki-cli or ~/.local/state/anki-cli)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    ensure = sub.add_parser("ready", help="Check headless collection readiness.")
    ensure.add_argument("--timeout", type=float, default=30.0, help="Headless network I/O timeout in seconds.")
    ensure.set_defaults(func=cmd_ready)

    enqueue = sub.add_parser("enqueue")
    enqueue_sub = enqueue.add_subparsers(dest="enqueue_command", required=True)
    upsert = enqueue_sub.add_parser("upsert")
    upsert.add_argument("--deck", required=True)
    upsert.add_argument("--front")
    upsert.add_argument("--front-file")
    upsert.add_argument("--back")
    upsert.add_argument("--back-file")
    upsert.add_argument("--external-id")
    upsert.add_argument("--extra")
    upsert.add_argument("--extra-file")
    upsert.add_argument("--source-title")
    upsert.add_argument("--source-uri")
    upsert.add_argument("--source-locator")
    upsert.add_argument("--source-hash")
    upsert.add_argument("--tags", nargs="*", default=[])
    upsert.add_argument("--render-mode", default="markdown-safe", choices=["plain", "markdown-safe", "html"])
    upsert.add_argument("--metadata-json")
    upsert.add_argument("--metadata-file")
    upsert.add_argument("--preview-html", help="Write a local HTML preview of the rendered card package.")
    upsert.add_argument("--no-enqueue", action="store_true", help="Build/validate input and optional preview without writing a queue job.")
    upsert.add_argument(
        "--media-manifest",
        action="append",
        help="JSON list or {'media': [...]} of structured media items with field/path/kind/caption/source metadata.",
    )
    upsert.add_argument(
        "--front-media-file",
        action="append",
        help="Image/media file to store in Anki and append to the front; repeatable.",
    )
    upsert.add_argument(
        "--back-media-file",
        action="append",
        help="Image/media file to store in Anki and append to the back; repeatable.",
    )
    upsert.add_argument("--notetype", default=DEFAULT_NOTETYPE)
    upsert.add_argument("--agent", default="codex")
    upsert.set_defaults(func=cmd_enqueue_upsert)

    drain = sub.add_parser("drain")
    drain.add_argument("--dry-run", action="store_true")
    drain.add_argument("--timeout", type=float, default=60.0, help="Headless sync network I/O timeout in seconds.")
    drain.add_argument("--limit", type=int)
    drain.add_argument("--sync", action="store_true")
    drain.set_defaults(func=cmd_drain)

    status = sub.add_parser("status")
    status.add_argument("--limit", type=int, default=5)
    status.set_defaults(func=cmd_status)

    decks = sub.add_parser("decks", help="List live Anki decks.")
    decks.add_argument("--counts", action="store_true", help="Include live card counts per deck.")
    decks.set_defaults(func=cmd_decks)

    move_deck = sub.add_parser("move-deck", help="Move live cards from one deck to another without recreating notes.")
    move_deck.add_argument("--from-deck", required=True)
    move_deck.add_argument("--to-deck", required=True)
    move_deck.add_argument("--query", help="Additional Anki search terms to intersect with --from-deck.")
    move_deck.add_argument("--dry-run", action="store_true")
    move_deck.add_argument("--sync-first", action="store_true")
    move_deck.add_argument("--sync", action="store_true", help="Sync after moving cards.")
    move_deck.set_defaults(func=cmd_move_deck)

    gap = sub.add_parser("gap", help="Read-only review telemetry workflows for missing-gap detection.")
    gap_sub = gap.add_subparsers(dest="gap_command", required=True)
    gap_export = gap_sub.add_parser("export", help="Export repeated review-friction signals for Anki Gap Briefs.")
    gap_export.add_argument("--sync-first", action="store_true", help="Sync before reading review telemetry.")
    gap_export.add_argument("--days", type=int, default=30, help="Main review-history window in days.")
    gap_export.add_argument("--recent-days", type=int, default=7, help="Recent-friction window in days; must be <= --days.")
    gap_export.add_argument("--limit", type=int, default=80, help="Maximum candidate cards to include after scoring.")
    gap_export.add_argument("--max-pool", type=int, default=500, help="Maximum raw candidate card IDs to inspect.")
    gap_export.add_argument("--include-text", choices=["none", "preview", "full"], default="preview")
    gap_export.add_argument("--max-field-chars", type=int, default=700)
    gap_export.add_argument("--min-reps", type=int, default=3, help="Reps threshold for mature-card friction.")
    gap_export.add_argument("--min-interval", type=int, default=7, help="Interval-days threshold for mature-card friction.")
    gap_export.add_argument("--deck", action="append", help="Restrict export to a deck; repeatable.")
    gap_export.add_argument("--query", help="Additional Anki search terms to intersect with each telemetry query.")
    gap_export.set_defaults(func=cmd_gap_export)

    find = sub.add_parser("find")
    mode = find.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ledger", action="store_true")
    mode.add_argument("--live", action="store_true")
    find.add_argument("--external-id")
    find.add_argument("--deck")
    find.add_argument("--tag", action="append")
    find.add_argument("--marked", action="store_true", help="Find Anki's marked cards/notes (tag:marked).")
    find.add_argument("--flag", type=int, choices=[1, 2, 3, 4], help="Find cards/notes with a given Anki flag color number.")
    find.add_argument("--sync-first", action="store_true", help="Sync before live search, useful after marking cards on AnkiMobile.")
    find.add_argument("--notetype", help="Restrict to a note type. Omitted by default so mobile Mark/Flag searches see all decks.")
    find.set_defaults(func=cmd_find)

    clear = sub.add_parser("clear")
    clear.add_argument("--external-id")
    clear.add_argument("--deck")
    clear.add_argument("--tag", action="append", help="Restrict to notes that have this tag; repeatable.")
    clear.add_argument("--marked", action="store_true", help="Clear Anki's marked state by removing tag:marked from matched notes.")
    clear.add_argument("--flag", type=int, choices=[1, 2, 3, 4], help="Clear a given Anki flag color number from matched cards.")
    clear.add_argument("--remove-tag", action="append", help="Additional tag to remove from matched notes; repeatable.")
    clear.add_argument("--sync-first", action="store_true")
    clear.add_argument("--sync", action="store_true", help="Sync after clearing tags.")
    clear.add_argument("--dry-run", action="store_true")
    clear.add_argument("--notetype", help="Restrict to a note type. Omitted by default.")
    clear.set_defaults(func=cmd_clear)

    sync = sub.add_parser("sync")
    sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        with client_scope():
            return int(args.func(args))
    except Exception as exc:
        print_json({"ok": False, "error": str(exc), "error_type": exc.__class__.__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
