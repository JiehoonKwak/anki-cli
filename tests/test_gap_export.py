from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from anki_cli.headless import HeadlessClient
from anki_cli.gap import build_gap_export, review_stats, strip_html, tokenize


NOW = datetime(2026, 6, 21, tzinfo=timezone.utc)


def rev(days_ago: int, ease: int, *, time: int = 1000) -> dict[str, int]:
    ts = int((NOW - timedelta(days=days_ago)).timestamp() * 1000)
    return {"id": ts, "ease": ease, "ivl": 1, "lastIvl": 1, "factor": 2500, "time": time, "type": 1, "usn": 0}


class FakeGapClient:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.cards = {
            101: {
                "cardId": 101,
                "note": 201,
                "deckName": "flashcard::statistics",
                "modelName": "Basic",
                "reps": 1,
                "interval": 0,
                "lapses": 0,
                "queue": 2,
                "type": 2,
            },
            102: {
                "cardId": 102,
                "note": 202,
                "deckName": "flashcard::statistics",
                "modelName": "Basic",
                "reps": 8,
                "interval": 15,
                "lapses": 0,
                "queue": 2,
                "type": 2,
            },
            103: {
                "cardId": 103,
                "note": 203,
                "deckName": "flashcard::statistics",
                "modelName": "Basic",
                "reps": 7,
                "interval": 12,
                "lapses": 0,
                "queue": 2,
                "type": 2,
            },
        }
        self.notes = {
            201: {
                "noteId": 201,
                "tags": ["topic::causal_inference"],
                "fields": {
                    "Front": {"value": "새 카드: conditioning은 무엇인가?"},
                    "Back": {"value": "변수의 특정 값을 고정해 보는 것이다."},
                    "SourceTitle": {"value": "Causal lecture"},
                },
            },
            202: {
                "noteId": 202,
                "tags": ["topic::causal_inference"],
                "fields": {
                    "Front": {"value": "conditioning이 causal graph에서 path를 여는 경우는?"},
                    "Back": {"value": "collider에 conditioning하면 닫혀 있던 path가 열린다."},
                    "SourceTitle": {"value": "Causal lecture"},
                },
            },
            203: {
                "noteId": 203,
                "tags": ["topic::causal_inference"],
                "fields": {
                    "Front": {"value": "confounder control과 collider conditioning은 왜 다른가?"},
                    "Back": {"value": "confounder는 열린 backdoor path를 닫지만 collider는 닫힌 path를 연다."},
                    "SourceTitle": {"value": "Causal lecture"},
                },
            },
        }
        self.reviews = {
            "101": [rev(2, 1)],
            "102": [rev(2, 1), rev(10, 2), rev(20, 3)],
            "103": [rev(5, 2), rev(12, 2), rev(18, 2)],
        }

    def find_cards(self, query: str) -> list[int]:
        self.queries.append(query)
        if "tag:marked" in query or "flag:1" in query:
            raise AssertionError("Gap export should not query explicit mark/flag signals")
        if query.endswith("rated:7:1"):
            return [101, 102]
        if query.endswith("rated:7:2"):
            return [103]
        if query.endswith("rated:30:1"):
            return [101, 102]
        if query.endswith("rated:30:2"):
            return [102, 103]
        if query.endswith("prop:lapses>0") or query.endswith("tag:leech"):
            return []
        if query.endswith("is:due"):
            return [102]
        if query.endswith("is:learn") or query.endswith("is:new"):
            return []
        return []

    def cards_info(self, cards: list[int]) -> list[dict[str, Any]]:
        return [self.cards[card] for card in cards]

    def notes_info(self, notes: list[int] | None = None, query: str | None = None) -> list[dict[str, Any]]:
        assert query is None
        return [self.notes[note] for note in notes or []]

    def get_reviews_of_cards(self, cards: list[int]) -> dict[str, list[dict[str, Any]]]:
        return {str(card): self.reviews[str(card)] for card in cards}


def test_review_stats_counts_recent_and_window_again_hard() -> None:
    stats = review_stats([rev(1, 1), rev(3, 2), rev(20, 1), rev(40, 1)], now=NOW, days=30, recent_days=7)

    assert stats["again_recent"] == 1
    assert stats["hard_recent"] == 1
    assert stats["again_window"] == 2
    assert stats["window_total"] == 3


def test_learning_button_two_is_not_counted_as_hard() -> None:
    learning_good = rev(1, 2)
    learning_good["type"] = 0
    stats = review_stats([learning_good, rev(2, 2)], now=NOW, days=30, recent_days=7)

    assert stats["hard_recent"] == 1
    assert stats["hard_window"] == 1


def test_gap_export_excludes_single_new_again_and_clusters_mature_friction() -> None:
    export = build_gap_export(cast(HeadlessClient, FakeGapClient()), now=NOW, days=30, recent_days=7, include_text="preview")

    candidate_ids = {item["card_id"] for item in export["candidates"]}
    assert 101 not in candidate_ids  # single new-card Again is normal learning noise
    assert {102, 103} <= candidate_ids
    assert export["scope"]["explicit_user_signals_excluded"] == ["tag:marked", "flag:1"]
    assert export["counts"]["excluded"] == {"low_signal_or_normal_learning_noise": 1}
    assert any(cluster["kind"] == "source" and cluster["label"] == "Causal lecture" for cluster in export["clusters"])
    assert any(cluster["kind"] == "tag" and cluster["label"] == "topic::causal_inference" for cluster in export["clusters"])


def test_text_helpers_strip_html_and_find_domain_tokens() -> None:
    assert strip_html("<p>collider&nbsp;conditioning</p>") == "collider conditioning"
    tokens = tokenize("confounder control과 collider conditioning은 왜 다른가?")
    assert {"confounder", "collider", "conditioning"} <= tokens
