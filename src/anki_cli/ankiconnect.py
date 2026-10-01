from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AnkiConnectError(RuntimeError):
    """Raised when AnkiConnect returns an error or is unreachable."""


@dataclass(frozen=True)
class AnkiConnectClient:
    url: str = "http://127.0.0.1:8765"
    api_key: str | None = None
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> "AnkiConnectClient":
        return cls(
            url=os.environ.get("ANKI_CLI_ANKICONNECT_URL", "http://127.0.0.1:8765"),
            api_key=os.environ.get("ANKI_CLI_ANKICONNECT_KEY") or None,
            timeout=float(os.environ.get("ANKI_CLI_ANKICONNECT_TIMEOUT", "10")),
        )

    def request(self, action: str, params: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {
            "action": action,
            "version": 6,
            "params": params or {},
        }
        if self.api_key is not None:
            payload["key"] = self.api_key

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AnkiConnectError(f"AnkiConnect unavailable at {self.url}: {exc}") from exc

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AnkiConnectError(f"AnkiConnect returned non-JSON response: {body!r}") from exc

        if isinstance(decoded, dict) and decoded.get("error") is not None:
            raise AnkiConnectError(str(decoded["error"]))
        if not isinstance(decoded, dict) or "result" not in decoded:
            raise AnkiConnectError(f"Unexpected AnkiConnect response: {decoded!r}")
        return decoded["result"]

    def reachable(self) -> bool:
        try:
            self.request("version")
            return True
        except AnkiConnectError:
            return False

    def version(self) -> int:
        return int(self.request("version"))

    def deck_names(self) -> list[str]:
        return list(self.request("deckNames"))

    def create_deck(self, deck: str) -> int:
        return int(self.request("createDeck", {"deck": deck}))

    def model_names(self) -> list[str]:
        return list(self.request("modelNames"))

    def model_field_names(self, model_name: str) -> list[str]:
        return list(self.request("modelFieldNames", {"modelName": model_name}))

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front_template: str,
        back_template: str,
        css: str,
    ) -> dict[str, Any]:
        return dict(
            self.request(
                "createModel",
                {
                    "modelName": model_name,
                    "inOrderFields": fields,
                    "cardTemplates": [
                        {
                            "Name": "Card 1",
                            "Front": front_template,
                            "Back": back_template,
                        }
                    ],
                    "css": css,
                    "isCloze": False,
                },
            )
        )

    def find_notes(self, query: str) -> list[int]:
        return [int(note_id) for note_id in self.request("findNotes", {"query": query})]

    def find_cards(self, query: str) -> list[int]:
        return [int(card_id) for card_id in self.request("findCards", {"query": query})]

    def cards_info(self, cards: list[int]) -> list[dict[str, Any]]:
        return list(self.request("cardsInfo", {"cards": cards}))

    def get_reviews_of_cards(self, cards: list[int]) -> dict[str, list[dict[str, Any]]]:
        return dict(self.request("getReviewsOfCards", {"cards": cards}))

    def change_deck(self, cards: list[int], deck: str) -> Any:
        return self.request("changeDeck", {"cards": cards, "deck": deck})

    def notes_info(
        self,
        notes: list[int] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        if query is not None:
            if notes is not None:
                raise ValueError("notes and query are mutually exclusive")
            notes = self.find_notes(query)
        params: dict[str, Any] = {}
        if notes is not None:
            params["notes"] = notes
        return list(self.request("notesInfo", params))

    def add_note(
        self,
        deck: str,
        model_name: str,
        fields: dict[str, str],
        tags: list[str],
    ) -> int:
        return int(
            self.request(
                "addNote",
                {
                    "note": {
                        "deckName": deck,
                        "modelName": model_name,
                        "fields": fields,
                        "tags": tags,
                        "options": {
                            "allowDuplicate": False,
                            "duplicateScope": "deck",
                            "duplicateScopeOptions": {
                                "deckName": deck,
                                "checkChildren": True,
                                "checkAllModels": False,
                            },
                        },
                    }
                },
            )
        )

    def update_note(self, note_id: int, fields: dict[str, str], tags: list[str] | None = None) -> None:
        note: dict[str, Any] = {"id": note_id, "fields": fields}
        if tags is not None:
            note["tags"] = tags
        self.request("updateNote", {"note": note})

    def store_media_file(self, filename: str, path: str) -> str:
        data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        return str(self.request("storeMediaFile", {"filename": filename, "data": data}))

    def add_tags(self, note_ids: list[int], tags: list[str]) -> None:
        if tags:
            self.request("addTags", {"notes": note_ids, "tags": " ".join(tags)})

    def remove_tags(self, note_ids: list[int], tags: list[str]) -> None:
        if tags:
            self.request("removeTags", {"notes": note_ids, "tags": " ".join(tags)})

    def set_card_flag(self, card_ids: list[int], flag: int) -> Any:
        results = []
        for card_id in card_ids:
            results.append(self.request("setSpecificValueOfCard", {"card": card_id, "keys": ["flags"], "newValues": [flag]}))
        return results

    def sync(self) -> Any:
        return self.request("sync")
