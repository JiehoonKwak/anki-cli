from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from anki_cli.cli import default_state_root, main


def enqueue_args() -> list[str]:
    return [
        "enqueue",
        "upsert",
        "--deck",
        "test",
        "--front",
        "question",
        "--back",
        "answer",
    ]


def test_default_state_stays_outside_checkout(tmp_path, monkeypatch, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    state_home = tmp_path / "private-state"
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    previous_umask = os.umask(0o022)
    try:
        assert main(enqueue_args()) == 0
    finally:
        os.umask(previous_umask)
    report = json.loads(capsys.readouterr().out)
    assert Path(report["path"]).parent == state_home / "anki-cli/state/queue/pending"
    assert stat.S_IMODE((state_home / "anki-cli").stat().st_mode) == 0o700
    assert not (checkout / "state").exists()


def test_explicit_root_preserves_state_layout(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "default"))
    root = tmp_path / "chosen"

    assert main(["--root", str(root), *enqueue_args()]) == 0
    report = json.loads(capsys.readouterr().out)
    assert Path(report["path"]).parent == root / "state/queue/pending"
    assert not (tmp_path / "default").exists()


def test_default_state_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_state_root() == tmp_path / ".local/state/anki-cli"


def test_relative_xdg_state_home_does_not_put_state_in_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "state")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_state_root() == tmp_path / ".local/state/anki-cli"


@pytest.mark.parametrize(
    "args",
    [
        [*enqueue_args(), "--commit"],
        [*enqueue_args(), "--push"],
        ["drain", "--commit"],
        ["drain", "--push"],
    ],
)
def test_git_transport_flags_are_rejected(args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
