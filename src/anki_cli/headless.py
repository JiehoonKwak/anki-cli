"""Local collection access through Anki's official non-Qt library."""

from __future__ import annotations

import fcntl
import io
import os
import pickle
import platform
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from anki.collection import Collection
from anki.sync import SyncAuth


class ProfileReader(pickle.Unpickler):
    """Read Qt byte arrays without importing Qt or executing pickle globals."""

    def find_class(self, module: str, name: str) -> Any:
        if module.startswith(("PyQt", "PySide")) and name == "QByteArray":
            return bytes
        raise pickle.UnpicklingError(f"unsupported profile value: {module}.{name}")


def read_profiles(base: Path) -> dict[str, dict[str, Any]]:
    prefs = base / "prefs21.db"
    if not prefs.exists():
        return {}
    with sqlite3.connect(prefs.as_uri() + "?mode=ro", uri=True) as db:
        return {
            name: ProfileReader(io.BytesIO(data)).load()
            for name, data in db.execute("select name, data from profiles")
        }


def default_base() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/Anki2"
    return (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "Anki2"
    )


def collection_target() -> tuple[Path, dict[str, Any]]:
    explicit = os.environ.get("ANKI_CLI_COLLECTION")
    base = (
        Path(os.environ.get("ANKI_CLI_BASE", str(default_base())))
        .expanduser()
        .resolve()
    )
    if explicit:
        path = Path(explicit).expanduser().resolve()
        # Only use a profile's credentials when it owns the exact collection.
        profiles = read_profiles(path.parent.parent)
        return path, profiles.get(path.parent.name, {})
    profiles = read_profiles(base)
    name = os.environ.get("ANKI_CLI_PROFILE") or profiles.get("_global", {}).get(
        "last_loaded_profile_name"
    )
    names = [key for key in profiles if key != "_global"]
    if name is None and len(names) == 1:
        name = names[0]
    if name not in names:
        raise RuntimeError(
            "select a local Anki profile with ANKI_CLI_PROFILE or ANKI_CLI_COLLECTION"
        )
    path = (base / name / "collection.anki2").resolve()
    if path.parent.parent != base:
        raise RuntimeError("invalid Anki profile path")
    return path, profiles[name]


def collection_in_use(path: Path) -> bool:
    """Check file ownership, including desktop Anki and other library clients."""
    if platform.system() == "Darwin":
        result = subprocess.run(
            ["/usr/sbin/lsof", "-t", "--", str(path)], capture_output=True, text=True
        )
        if result.returncode not in (0, 1):
            raise RuntimeError("could not check collection ownership")
        return any(int(pid) != os.getpid() for pid in result.stdout.split())
    # Linux: check this user's open descriptors without depending on lsof.
    for process in Path("/proc").glob("[0-9]*"):
        if process.name == str(os.getpid()):
            continue
        try:
            for fd in (process / "fd").iterdir():
                try:
                    if fd.resolve() == path:
                        return True
                except OSError:
                    continue
        except (PermissionError, FileNotFoundError):
            continue
    return False


class HeadlessClient:
    backend = "headless"

    def __init__(self, path: Path, profile: dict[str, Any] | None = None) -> None:
        self.path = path.resolve()
        self.url = self.path.as_uri()
        self.profile = profile or {}
        if not self.path.is_file():
            raise RuntimeError(f"collection does not exist: {self.path}")
        self._lock = self.path.with_suffix(".anki-cli.lock").open("a")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if collection_in_use(self.path):
                raise RuntimeError(
                    "collection is open in another process; use its existing AnkiConnect connection or retry after closing Anki"
                )
            self.col = Collection(str(self.path))
        except BaseException:
            self._lock.close()
            raise
        self._backed_up = False

    def close(self) -> None:
        try:
            self.col.close()
        finally:
            self._lock.close()

    def _before_write(self) -> None:
        if not self._backed_up:
            backup_folder = self.path.parent / "backups"
            backup_folder.mkdir(exist_ok=True)
            self.col.create_backup(
                backup_folder=str(backup_folder), force=True, wait_for_completion=True
            )
            self._backed_up = True

    def reachable(self) -> bool:
        return self.col.db is not None

    def version(self) -> str:
        from importlib.metadata import version

        return version("anki")

    def deck_names(self) -> list[str]:
        return [deck.name for deck in self.col.decks.all_names_and_ids()]

    def create_deck(self, deck: str) -> int:
        self._before_write()
        return int(self.col.decks.id(deck))

    def model_names(self) -> list[str]:
        return [model.name for model in self.col.models.all_names_and_ids()]

    def _model(self, name: str) -> dict[str, Any]:
        model = self.col.models.by_name(name)
        if model is None:
            raise ValueError(f"unknown note type: {name}")
        return model

    def model_field_names(self, model_name: str) -> list[str]:
        return self.col.models.field_names(self._model(model_name))

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        front_template: str,
        back_template: str,
        css: str,
    ) -> dict[str, Any]:
        self._before_write()
        model = self.col.models.new(model_name)
        for field in fields:
            self.col.models.add_field(model, self.col.models.new_field(field))
        template = self.col.models.new_template("Card 1")
        template.update(qfmt=front_template, afmt=back_template)
        self.col.models.add_template(model, template)
        model["css"] = css
        self.col.models.add(model)
        return model

    def find_notes(self, query: str) -> list[int]:
        return list(self.col.find_notes(query))

    def find_cards(self, query: str) -> list[int]:
        return list(self.col.find_cards(query))

    def notes_info(
        self, notes: list[int] | None = None, query: str | None = None
    ) -> list[dict[str, Any]]:
        if query is not None:
            if notes is not None:
                raise ValueError("notes and query are mutually exclusive")
            notes = self.find_notes(query)
        result = []
        for nid in notes or []:
            note = self.col.get_note(nid)
            result.append(
                {
                    "noteId": note.id,
                    "tags": note.tags,
                    "modelName": note.note_type()["name"],
                    "fields": {
                        name: {"value": value, "order": index}
                        for index, (name, value) in enumerate(note.items())
                    },
                    "cards": [card.id for card in note.cards()],
                }
            )
        return result

    def cards_info(self, cards: list[int]) -> list[dict[str, Any]]:
        result = []
        for cid in cards:
            card = self.col.get_card(cid)
            note = card.note()
            result.append(
                {
                    "cardId": card.id,
                    "note": card.nid,
                    "ord": card.ord,
                    "deckName": self.col.decks.name(card.did),
                    "modelName": note.note_type()["name"],
                    "fields": {
                        name: {"value": value, "order": index}
                        for index, (name, value) in enumerate(note.items())
                    },
                    "question": card.question(),
                    "answer": card.answer(),
                    "css": note.note_type()["css"],
                    "type": card.type,
                    "queue": card.queue,
                    "due": card.due,
                    "interval": card.ivl,
                    "factor": card.factor,
                    "reps": card.reps,
                    "lapses": card.lapses,
                    "left": card.left,
                    "mod": card.mod,
                    "flags": card.flags,
                }
            )
        return result

    def add_note(
        self, deck: str, model_name: str, fields: dict[str, str], tags: list[str]
    ) -> int:
        self._before_write()
        note = self.col.new_note(self._model(model_name))
        for name, value in fields.items():
            note[name] = value
        note.tags = tags
        # ExternalID is the first field; enforce its uniqueness across decks.
        if self.find_notes(f'note:"{model_name}" ExternalID:"{fields["ExternalID"]}"'):
            raise RuntimeError("duplicate ExternalID")
        self.col.add_note(note, self.col.decks.id(deck))
        return int(note.id)

    def update_note(
        self, note_id: int, fields: dict[str, str], tags: list[str] | None = None
    ) -> None:
        self._before_write()
        note = self.col.get_note(note_id)
        for name, value in fields.items():
            note[name] = value
        if tags is not None:
            note.tags = tags
        self.col.update_note(note)

    def store_media_file(self, filename: str, path: str) -> str:
        self._before_write()
        actual = self.col.media.write_data(filename, Path(path).read_bytes())
        if actual != filename:
            raise RuntimeError(f"media filename changed: {filename} -> {actual}")
        return actual

    def change_deck(self, cards: list[int], deck: str) -> None:
        self._before_write()
        self.col.set_deck(cards, self.col.decks.id(deck))

    def add_tags(self, note_ids: list[int], tags: list[str]) -> None:
        if tags:
            self._before_write()
            self.col.tags.bulk_add(note_ids, " ".join(tags))

    def remove_tags(self, note_ids: list[int], tags: list[str]) -> None:
        if tags:
            self._before_write()
            self.col.tags.bulk_remove(note_ids, " ".join(tags))

    def set_card_flag(self, card_ids: list[int], flag: int) -> None:
        self._before_write()
        self.col.set_user_flag_for_cards(flag, card_ids)

    def get_reviews_of_cards(self, cards: list[int]) -> dict[str, list[dict[str, int]]]:
        # Read-only SQL preserves AnkiConnect's millisecond IDs and raw revlog shape.
        keys = ["id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type"]
        return {
            str(cid): [
                dict(zip(keys, row))
                for row in self.col.db.all(
                    "select id,cid,usn,ease,ivl,lastIvl,factor,time,type from revlog where cid=? order by id",
                    cid,
                )
            ]
            for cid in cards
        }

    def sync(self) -> dict[str, Any]:
        key = self.profile.get("syncKey")
        if not key:
            raise RuntimeError(
                "sync authentication is not configured in this collection's Anki profile"
            )
        self._before_write()
        auth = SyncAuth(
            hkey=key,
            endpoint=self.profile.get("currentSyncUrl")
            or self.profile.get("customSyncUrl")
            or None,
            io_timeout_secs=self.profile.get("networkTimeout") or 60,
        )
        out = self.col.sync_collection(auth, False)
        if out.required not in (out.NO_CHANGES, out.NORMAL_SYNC):
            raise RuntimeError(
                "full sync required; resolve upload/download direction in Anki Desktop"
            )
        # Use the redirect returned by collection sync for media, too.
        if out.new_endpoint:
            auth.endpoint = out.new_endpoint
        if self.profile.get("syncMedia", True):
            self.col.sync_media(auth)
        return {
            "collection": "synced",
            "media": "synced" if self.profile.get("syncMedia", True) else "disabled",
        }
