from __future__ import annotations

import json
import os
import pickle
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from anki.collection import Collection
from anki.sync_pb2 import SyncCollectionResponse

from anki_cli.backend import client_scope, get_client
from anki_cli.cli import core_card_state, main, upsert_job
from anki_cli.headless import HeadlessClient, collection_target, read_profiles
from anki_cli.schema import build_upsert_job


@pytest.fixture
def collection_path(tmp_path):
    path = tmp_path / "profile" / "collection.anki2"
    path.parent.mkdir()
    Collection(str(path)).close()
    return path


@pytest.fixture
def client(collection_path):
    client = HeadlessClient(collection_path)
    yield client
    client.close()


def job(
    external_id="test:one", deck="test::biology", front="질문", back="답변", tags=None
):
    return build_upsert_job(
        deck=deck,
        external_id=external_id,
        front=front,
        back=back,
        tags=tags or ["test"],
        agent="codex",
        render_mode="html",
    )


def test_upsert_preserves_schedule_tags_and_identity(client):
    result = upsert_job(client, job())
    nid = result["note_id"]
    cid = client.notes_info(notes=[nid])[0]["cards"][0]
    card = client.col.get_card(cid)
    card.type = 2
    card.queue = 2
    card.due = 42
    card.ivl = 10
    card.reps = 8
    card.lapses = 2
    card.factor = 2500
    client.col.update_card(card)
    client.add_tags([nid], ["marked"])
    before = client.cards_info([cid])[0]
    changed = upsert_job(client, job(back="새 답변", tags=["new"]))
    after = client.cards_info([cid])[0]
    assert changed["action"] == "updated"
    assert changed["note_id"] == nid
    assert len(client.find_notes("")) == 1
    assert core_card_state(before) == core_card_state(after)
    assert before["factor"] == after["factor"]
    assert set(client.notes_info(notes=[nid])[0]["tags"]) == {"marked", "test", "new"}
    assert "새 답변" in after["answer"]
    assert after["deckName"] == "test::biology"
    assert list((client.path.parent / "backups").glob("*.colpkg"))


def test_deck_move_flags_and_tags_preserve_schedule(client):
    nid = upsert_job(client, job())["note_id"]
    cid = client.find_cards("")[0]
    before = core_card_state(client.cards_info([cid])[0])
    client.create_deck("moved")
    client.change_deck([cid], "moved")
    client.set_card_flag([cid], 1)
    client.add_tags([nid], ["marked", "keep"])
    assert client.find_cards("flag:1") == [cid]
    assert client.find_notes("tag:marked") == [nid]
    client.remove_tags([nid], ["marked"])
    client.set_card_flag([cid], 0)
    assert not client.find_cards("flag:1")
    assert not client.find_notes("tag:marked")
    assert client.find_notes("tag:keep") == [nid]
    assert before == core_card_state(client.cards_info([cid])[0])


def test_media_and_unicode_math_roundtrip(client, tmp_path):
    media = tmp_path / "diagram.svg"
    media.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert client.store_media_file("diagram.svg", str(media)) == "diagram.svg"
    assert (
        Path(client.col.media.dir()) / "diagram.svg"
    ).read_bytes() == media.read_bytes()
    result = upsert_job(client, job(front=r"한글 \(H_3\)", back="<b>PRC2</b>"))
    info = client.notes_info(notes=[result["note_id"]])[0]
    assert "한글" in info["fields"]["Front"]["value"]
    assert r"\(H_3\)" in info["fields"]["Front"]["value"]
    assert client.model_field_names("AnkiCLI-Basic-v1")[0] == "ExternalID"


def test_review_telemetry_preserves_millisecond_ids(client):
    upsert_job(client, job())
    cid = client.find_cards("")[0]
    # Test fixture only: production implementation never writes revlog SQL.
    client.col.db.execute(
        "insert into revlog values (?,?,?,?,?,?,?,?,?)",
        1790810000000,
        cid,
        -1,
        2,
        10,
        3,
        2500,
        1200,
        1,
    )
    assert client.get_reviews_of_cards([cid])[str(cid)] == [
        {
            "id": 1790810000000,
            "cid": cid,
            "usn": -1,
            "ease": 2,
            "ivl": 10,
            "lastIvl": 3,
            "factor": 2500,
            "time": 1200,
            "type": 1,
        }
    ]
    assert client.find_cards("rated:30:2") == [cid]


def test_cli_clear_flag_is_scoped_to_external_id(client, monkeypatch, capsys):
    first = upsert_job(client, job())["note_id"]
    second = upsert_job(client, job("test:two"))["note_id"]
    cids = client.find_cards("")
    client.set_card_flag(cids, 1)
    monkeypatch.setattr("anki_cli.cli.get_client", lambda: client)
    assert main(["clear", "--external-id", "test:one", "--flag", "1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["card_ids"] == client.notes_info(notes=[first])[0]["cards"]
    assert client.find_notes("flag:1") == [second]


def test_parallel_headless_open_is_rejected(client):
    with pytest.raises(BlockingIOError):
        HeadlessClient(client.path)


def test_external_open_collection_is_rejected(collection_path):
    code = 'from anki.collection import Collection; import sys; c=Collection(sys.argv[1]); print("ready",flush=True); sys.stdin.read(); c.close()'
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(collection_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(RuntimeError, match="open in another process"):
            HeadlessClient(collection_path)
    finally:
        proc.communicate("close", timeout=10)


def test_missing_collection_is_not_created(tmp_path):
    path = tmp_path / "missing.anki2"
    with pytest.raises(RuntimeError, match="does not exist"):
        HeadlessClient(path)
    assert not path.exists()


def test_scope_closes_collection_on_failure(collection_path, monkeypatch):
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    with pytest.raises(ValueError):
        with client_scope():
            client = get_client()
            raise ValueError("test")
    assert not client.reachable()
    HeadlessClient(collection_path).close()


def test_sync_requires_local_profile_auth(client):
    with pytest.raises(RuntimeError, match="authentication"):
        client.sync()


@pytest.mark.parametrize(
    "required",
    [
        SyncCollectionResponse.FULL_SYNC,
        SyncCollectionResponse.FULL_UPLOAD,
        SyncCollectionResponse.FULL_DOWNLOAD,
    ],
)
def test_full_sync_never_chooses_upload_or_download(client, monkeypatch, required):
    client.profile = {"syncKey": "fixture-key"}
    monkeypatch.setattr(
        client.col,
        "sync_collection",
        lambda auth, media: SyncCollectionResponse(required=required),
    )
    with pytest.raises(RuntimeError, match="full sync required"):
        client.sync()


def test_sync_waits_for_media_and_uses_redirect(client, monkeypatch):
    client.profile = {"syncKey": "fixture-key"}
    seen = []
    monkeypatch.setattr(
        client.col,
        "sync_collection",
        lambda auth, media: SyncCollectionResponse(
            required=SyncCollectionResponse.NORMAL_SYNC,
            new_endpoint="https://sync.example/",
        ),
    )
    monkeypatch.setattr(
        client.col, "sync_media", lambda auth: seen.append(auth.endpoint)
    )
    assert client.sync() == {"collection": "synced", "media": "synced"}
    assert seen == ["https://sync.example/"]
    monkeypatch.setattr(
        client.col,
        "sync_media",
        lambda auth: (_ for _ in ()).throw(RuntimeError("media failure")),
    )
    with pytest.raises(RuntimeError, match="media failure"):
        client.sync()


def test_profile_selection_is_explicit_when_ambiguous(tmp_path, monkeypatch):
    prefs = tmp_path / "prefs21.db"
    with sqlite3.connect(prefs) as db:
        db.execute("create table profiles(name text,data blob)")
        for name, data in [
            ("_global", {}),
            ("one", {"syncKey": "secret"}),
            ("two", {}),
        ]:
            db.execute("insert into profiles values (?,?)", (name, pickle.dumps(data)))
    monkeypatch.delenv("ANKI_CLI_COLLECTION", raising=False)
    monkeypatch.setenv("ANKI_CLI_BASE", str(tmp_path))
    with pytest.raises(RuntimeError, match="select a local"):
        collection_target()
    monkeypatch.setenv("ANKI_CLI_PROFILE", "one")
    path, profile = collection_target()
    assert path == tmp_path / "one/collection.anki2"
    assert profile["syncKey"] == "secret"


def test_profile_pickle_cannot_execute_code(tmp_path):
    class Malicious:
        def __reduce__(self):
            return (os.system, ("false",))

    with sqlite3.connect(tmp_path / "prefs21.db") as db:
        db.execute("create table profiles(name text,data blob)")
        db.execute(
            "insert into profiles values (?,?)", ("one", pickle.dumps(Malicious()))
        )
    with pytest.raises(pickle.UnpicklingError):
        read_profiles(tmp_path)


def test_headless_cli_queue_drain_and_reopen(
    collection_path, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    monkeypatch.setenv("ANKI_CLI_BACKEND", "headless")
    root = tmp_path / "queue"
    assert (
        main(
            [
                "--root",
                str(root),
                "enqueue",
                "upsert",
                "--deck",
                "test::biology",
                "--external-id",
                "test:cli",
                "--front",
                "한글 질문",
                "--back",
                "답변",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--root", str(root), "drain"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["backend"] == "headless"
    assert report["processed"][0]["action"] == "added"
    assert (
        main(["--root", str(root), "find", "--live", "--external-id", "test:cli"]) == 0
    )
    info = json.loads(capsys.readouterr().out)["items"][0]
    assert "한글 질문" in info["fields"]["Front"]["value"]
    assert main(["--root", str(root), "decks", "--counts"]) == 0
    assert "test::biology" in capsys.readouterr().out
    assert main(["--root", str(root), "gap", "export"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "anki_gap_export"


def test_drain_dry_run_does_not_open_collection(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "anki_cli.cli.get_client",
        lambda: pytest.fail("dry-run must not open collection"),
    )
    assert main(["--root", str(tmp_path), "drain", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


def test_sync_failure_keeps_applied_job_done(
    collection_path, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "enqueue",
                "upsert",
                "--deck",
                "test",
                "--front",
                "front",
                "--back",
                "back",
                "--external-id",
                "test:sync",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "drain", "--sync"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] and not output["sync"]["ok"]
    assert len(list((tmp_path / "state/queue/done").glob("*.json"))) == 1
    assert not list((tmp_path / "state/queue/pending").glob("*.json"))
    assert not list((tmp_path / "state/queue/failed").glob("*.json"))


def test_job_failure_is_separate_from_later_valid_job(
    collection_path, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    pending = tmp_path / "state/queue/pending"
    pending.mkdir(parents=True)
    (pending / "aaa.json").write_text("{}")
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "enqueue",
                "upsert",
                "--deck",
                "test",
                "--front",
                "front",
                "--back",
                "back",
                "--external-id",
                "test:good",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "drain"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert not output["ok"]
    assert any(item.get("action") == "added" for item in output["processed"])
    assert len(list((tmp_path / "state/queue/failed").glob("*.json"))) == 1


def test_missing_media_fails_without_creating_note(client, tmp_path):
    media = tmp_path / "test.png"
    media.write_bytes(b"fixture")
    payload = job()
    from anki_cli.schema import build_upsert_job

    payload = build_upsert_job(
        deck="test",
        external_id="test:media",
        front="front",
        back="back",
        back_media_files=[str(media)],
    )
    media.unlink()
    with pytest.raises(FileNotFoundError):
        upsert_job(client, payload)
    assert not client.find_notes("")


def test_cli_dry_run_clear_and_move_do_not_change_cards(client, monkeypatch, capsys):
    nid = upsert_job(client, job())["note_id"]
    cid = client.find_cards("")[0]
    client.add_tags([nid], ["marked"])
    client.set_card_flag([cid], 1)
    monkeypatch.setattr("anki_cli.cli.get_client", lambda: client)
    assert main(["clear", "--marked", "--flag", "1", "--dry-run"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "move-deck",
                "--from-deck",
                "test::biology",
                "--to-deck",
                "new",
                "--dry-run",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert client.find_notes("tag:marked") == [nid]
    assert client.find_cards("flag:1") == [cid]
    assert client.cards_info([cid])[0]["deckName"] == "test::biology"
    assert "new" not in client.deck_names()


def test_native_backend_errors_are_json(collection_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    assert main(["clear", "--flag", "1", "--deck", '"invalid']) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["error_type"] == "SearchError"


def test_queue_media_reaches_rendered_answer_and_media_store(
    collection_path, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    root = tmp_path / "jobs"
    media = tmp_path / "diagram.svg"
    media.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert (
        main(
            [
                "--root",
                str(root),
                "enqueue",
                "upsert",
                "--deck",
                "test",
                "--external-id",
                "test:figure",
                "--front",
                "어떤 기전인가?",
                "--back",
                r"\(H_3\)",
                "--render-mode",
                "html",
                "--back-media-file",
                str(media),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--root", str(root), "drain"]) == 0
    nid = json.loads(capsys.readouterr().out)["processed"][0]["note_id"]
    with client_scope():
        c = get_client()
        note = c.notes_info(notes=[nid])[0]
        meta = json.loads(note["fields"]["MetaJSON"]["value"].replace("&quot;", '"'))
        filename = meta["media"][0]["filename"]
        cid = note["cards"][0]
        assert filename in c.cards_info([cid])[0]["answer"]
        assert r"\(H_3\)" in c.cards_info([cid])[0]["answer"]
        assert (Path(c.col.media.dir()) / filename).read_bytes() == media.read_bytes()


@pytest.mark.parametrize("mode", ["auto", "ankiconnect", "gui"])
def test_legacy_gui_backend_is_rejected_before_collection_access(monkeypatch, mode):
    monkeypatch.setenv("ANKI_CLI_BACKEND", mode)
    monkeypatch.setattr(
        "anki_cli.backend.collection_target",
        lambda: pytest.fail("must fail before access"),
    )
    with client_scope(), pytest.raises(ValueError, match="only headless"):
        get_client()


def test_default_is_headless_without_backend_setting(collection_path, monkeypatch):
    monkeypatch.delenv("ANKI_CLI_BACKEND", raising=False)
    monkeypatch.setenv("ANKI_CLI_COLLECTION", str(collection_path))
    with client_scope():
        assert get_client().backend == "headless"


def test_app_launch_options_are_not_in_cli(tmp_path):
    with pytest.raises(SystemExit):
        main(["--root", str(tmp_path), "drain", "--ensure-anki"])
    with pytest.raises(SystemExit):
        main(["ensure-anki"])
