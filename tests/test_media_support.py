from __future__ import annotations

import html
import json
from pathlib import Path
from typing import cast

import pytest

from anki_cli.ankiconnect import AnkiConnectClient
from anki_cli.cli import main, rendered_fields, upsert_job
from anki_cli.schema import SchemaError, build_upsert_job, validate_job


class FakeClient:
    def __init__(self, *, add_note_deck: str | None = None) -> None:
        self.stored_media: list[dict[str, str]] = []
        self.added_note: dict | None = None
        self.card_deck = add_note_deck or "Deck"

    def deck_names(self) -> list[str]:
        return ["Deck"]

    def model_names(self) -> list[str]:
        return ["AnkiCLI-Basic-v1"]

    def model_field_names(self, model_name: str) -> list[str]:
        return [
            "ExternalID",
            "Front",
            "Back",
            "Extra",
            "SourceTitle",
            "SourceURI",
            "SourceLocator",
            "SourceHash",
            "MetaJSON",
        ]

    def notes_info(self, notes: list[int] | None = None, query: str | None = None):
        if query is not None:
            return []
        if notes == [123]:
            return [{"noteId": 123, "cards": [456], "fields": {}}]
        return []

    def cards_info(self, cards: list[int]) -> list[dict]:
        if cards == [456]:
            return [
                {
                    "cardId": 456,
                    "note": 123,
                    "ord": 0,
                    "deckName": self.card_deck,
                    "type": 0,
                    "queue": 0,
                    "due": 0,
                    "interval": 0,
                    "reps": 0,
                    "lapses": 0,
                }
            ]
        return []

    def change_deck(self, cards: list[int], deck: str):
        self.card_deck = deck

    def add_note(self, deck: str, model_name: str, fields: dict[str, str], tags: list[str]) -> int:
        self.added_note = {
            "deck": deck,
            "model_name": model_name,
            "fields": fields,
            "tags": tags,
        }
        return 123

    def store_media_file(self, filename: str, path: str) -> str:
        self.stored_media.append({"filename": filename, "path": path})
        return filename


def test_upsert_job_stores_front_media_and_renders_img_tag(tmp_path: Path) -> None:
    image = tmp_path / "Fig 4e.png"
    image.write_bytes(b"fake-png")

    job = build_upsert_job(
        deck="Deck",
        front="이 trajectory plot은 무엇을 연결해서 해석해야 하는가?",
        back="cell-state shift와 drug survival advantage의 연결을 본다.",
        external_id="paper:example:card:figure",
        front_media_files=[str(image)],
    )

    result = upsert_job(cast(AnkiConnectClient, FakeClient()), job)

    assert result["action"] == "added"
    fields = rendered_fields(job)
    assert '<img src="' in fields["Front"]
    assert 'alt="Fig 4e.png"' in fields["Front"]
    assert "Fig_4e" in fields["Front"]
    assert job["note"]["media"][0]["kind"] == "other"


def test_upsert_job_calls_ankiconnect_store_media_file_before_add_note(tmp_path: Path) -> None:
    image = tmp_path / "figure.png"
    image.write_bytes(b"fake-png")
    client = FakeClient()
    job = build_upsert_job(
        deck="Deck",
        front="front",
        back="back",
        external_id="paper:example:card:media-storage",
        front_media_files=[str(image)],
    )

    upsert_job(cast(AnkiConnectClient, client), job)

    assert client.stored_media == [
        {"filename": job["note"]["media"][0]["filename"], "path": str(image.resolve())}
    ]
    assert client.added_note is not None
    assert job["note"]["media"][0]["filename"] in client.added_note["fields"]["Front"]


def test_upsert_job_moves_generated_cards_to_target_deck_when_anki_uses_default() -> None:
    client = FakeClient(add_note_deck="Default")
    job = build_upsert_job(
        deck="Deck",
        front="front",
        back="back",
        external_id="concept:test-deck-move",
    )

    result = upsert_job(cast(AnkiConnectClient, client), job)

    assert result["deck_move"]["status"] == "moved"
    assert result["deck_move"]["current_decks_before_move"] == ["Default"]
    assert client.card_deck == "Deck"


def test_captioned_media_manifest_renders_figure_and_preserves_provenance(tmp_path: Path) -> None:
    image = tmp_path / "attention-slide.png"
    image.write_bytes(b"fake-png")

    job = build_upsert_job(
        deck="Deck",
        front="Transformer에서 attention diagram은 무엇을 보여주는가?",
        back="토큰들이 서로 다른 context 위치를 참조하며 representation을 갱신하는 구조를 보여준다.",
        external_id="video:transformer:intro:card:attention",
        media_items=[
            {
                "field": "back",
                "path": str(image),
                "kind": "screenshot",
                "caption": "Attention heads connect tokens to context positions.",
                "source_uri": "https://www.youtube.com/watch?v=abc&t=201s",
                "source_locator": "00:03:21",
                "alt": "Transformer attention lecture slide",
            }
        ],
    )

    validate_job(job)
    media = job["note"]["media"][0]
    assert media["kind"] == "screenshot"
    assert media["caption"] == "Attention heads connect tokens to context positions."
    assert media["source_locator"] == "00:03:21"

    fields = rendered_fields(job)
    assert "<figure" in fields["Back"]
    assert "<figcaption>" in fields["Back"]
    assert "Attention heads connect tokens to context positions." in fields["Back"]
    assert "00:03:21" in fields["Back"]
    assert "https://www.youtube.com/watch?v=abc&amp;t=201s" in fields["Back"]
    assert 'alt="Transformer attention lecture slide"' in fields["Back"]

    meta = json.loads(html.unescape(fields["MetaJSON"]))
    assert meta["media"] == [
        {
            "field": "back",
            "filename": media["filename"],
            "original_name": "attention-slide.png",
            "sha256": media["sha256"],
            "kind": "screenshot",
            "caption": "Attention heads connect tokens to context positions.",
            "source_uri": "https://www.youtube.com/watch?v=abc&t=201s",
            "source_locator": "00:03:21",
            "alt": "Transformer attention lecture slide",
        }
    ]
    assert "path" not in meta["media"][0]


def test_validate_job_rejects_unknown_media_kind(tmp_path: Path) -> None:
    image = tmp_path / "figure.png"
    image.write_bytes(b"fake-png")
    job = build_upsert_job(
        deck="Deck",
        front="front",
        back="back",
        media_items=[{"field": "front", "path": str(image), "kind": "screenshot"}],
    )
    job["note"]["media"][0]["kind"] = "photo"

    with pytest.raises(SchemaError, match="note.media.kind"):
        validate_job(job)


def test_cli_enqueue_accepts_structured_media_manifest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake-png")
    front = tmp_path / "front.md"
    back = tmp_path / "back.md"
    manifest = tmp_path / "media.json"
    front.write_text("front", encoding="utf-8")
    back.write_text("back", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "media": [
                    {
                        "field": "back",
                        "path": str(image),
                        "kind": "diagram",
                        "caption": "Generated diagram showing the minimal causal chain.",
                        "source_locator": "generated",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--root",
            str(root),
            "enqueue",
            "upsert",
            "--deck",
            "Deck",
            "--front-file",
            str(front),
            "--back-file",
            str(back),
            "--media-manifest",
            str(manifest),
        ]
    )

    assert exit_code == 0
    jobs = list((root / "state" / "queue" / "pending").glob("*.json"))
    assert len(jobs) == 1
    queued = json.loads(jobs[0].read_text(encoding="utf-8"))
    assert queued["note"]["media"][0]["kind"] == "diagram"
    assert queued["note"]["media"][0]["caption"] == "Generated diagram showing the minimal causal chain."


def test_cli_can_render_preview_html_without_enqueueing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    image = tmp_path / "causal.svg"
    image.write_text("<svg></svg>", encoding="utf-8")
    front = tmp_path / "front.md"
    back = tmp_path / "back.md"
    manifest = tmp_path / "media.json"
    preview = tmp_path / "preview.html"
    front.write_text("왜 X가 Y로 이어지는가?", encoding="utf-8")
    back.write_text("X -> mediator -> Y 구조라서 그렇다.", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            [
                {
                    "field": "back",
                    "path": str(image),
                    "kind": "diagram",
                    "caption": "Generated causal chain diagram.",
                    "source_locator": "generated",
                    "selection_reason": "Simpler than the source screenshot.",
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--root",
            str(root),
            "enqueue",
            "upsert",
            "--deck",
            "Deck",
            "--front-file",
            str(front),
            "--back-file",
            str(back),
            "--media-manifest",
            str(manifest),
            "--preview-html",
            str(preview),
            "--no-enqueue",
        ]
    )

    assert exit_code == 0
    assert not (root / "state" / "queue" / "pending").exists()
    html_preview = preview.read_text(encoding="utf-8")
    assert "왜 X가 Y로 이어지는가?" in html_preview
    assert "Generated causal chain diagram." in html_preview
    assert "Simpler than the source screenshot." in html_preview
    assert image.resolve().as_uri() in html_preview
