from __future__ import annotations

from typing import cast

from anki_cli.ankiconnect import AnkiConnectClient
from anki_cli.cli import move_cards_to_deck


class FakeDeckClient:
    def __init__(self, *, mutate_schedule: bool = False) -> None:
        self.mutate_schedule = mutate_schedule
        self.decks = ["Default"]
        self.cards = {
            101: {
                "cardId": 101,
                "note": 201,
                "ord": 0,
                "deckName": "Default",
                "type": 2,
                "queue": 2,
                "due": 42,
                "interval": 9,
                "reps": 3,
                "lapses": 1,
            }
        }

    def deck_names(self) -> list[str]:
        return self.decks

    def create_deck(self, deck: str) -> int:
        self.decks.append(deck)
        return len(self.decks)

    def cards_info(self, cards: list[int]) -> list[dict]:
        return [dict(self.cards[card]) for card in cards]

    def change_deck(self, cards: list[int], deck: str):
        for card in cards:
            self.cards[card]["deckName"] = deck
            if self.mutate_schedule:
                self.cards[card]["reps"] += 1


def test_move_cards_to_deck_preserves_scheduling_fields() -> None:
    client = FakeDeckClient()

    result = move_cards_to_deck(cast(AnkiConnectClient, client), [101], "flashcard::statistics")

    assert result["ok"] is True
    assert result["preserved_scheduling"] is True
    assert client.cards[101]["deckName"] == "flashcard::statistics"
    assert client.cards[101]["reps"] == 3


def test_move_cards_to_deck_detects_scheduling_mutation() -> None:
    client = FakeDeckClient(mutate_schedule=True)

    result = move_cards_to_deck(cast(AnkiConnectClient, client), [101], "flashcard::statistics")

    assert result["ok"] is False
    assert result["preserved_scheduling"] is False
    assert result["errors"] == ["card 101: scheduling changed"]


def test_move_cards_to_deck_dry_run_does_not_create_or_move() -> None:
    client = FakeDeckClient()

    result = move_cards_to_deck(cast(AnkiConnectClient, client), [101], "flashcard::statistics", dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["count"] == 1
    assert client.decks == ["Default"]
    assert client.cards[101]["deckName"] == "Default"
