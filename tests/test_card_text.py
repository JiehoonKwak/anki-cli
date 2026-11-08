from __future__ import annotations

from pathlib import Path

import pytest
from anki.collection import Collection

from anki_cli.card import MODEL_CSS
from anki_cli.cli import upsert_job
from anki_cli.headless import HeadlessClient
from anki_cli.render import render_field
from anki_cli.schema import SchemaError, build_upsert_job


def job(front: str = "질문", back: str = "답", mode: str = "html", **kwargs):
    return build_upsert_job(deck="Deck", front=front, back=back, render_mode=mode, agent="test", **kwargs)


def test_markdown_safe_keeps_mathjax_delimiters():
    rendered = render_field("관계 \\(p=\\hbar k\\) 와\n\n\\[\\frac{a<b}{2}\\]\n\n*강조*", "markdown-safe")
    assert "\\(p=\\hbar k\\)" in rendered
    assert "\\[\\frac{a&lt;b}{2}\\]" in rendered
    assert "<em>강조</em>" in rendered


def test_escape_eaten_by_writer_is_rejected():
    with pytest.raises(SchemaError, match="control character"):
        job(back="<div>\\[\\left(\\frac{E}{c}\right)^2\\]</div>")
    with pytest.raises(SchemaError, match="TeX command"):
        job(back="<div>\\[\\left(\\frac{E}{c}\night)^2\\]</div>")
    with pytest.raises(SchemaError, match="TeX command"):
        job(front="\\(\theta\\)")


def test_multiline_display_math_is_accepted():
    built = job(back="<div>\\[\na^2 + b^2\n= c^2\n\\]</div>")
    assert "a^2" in built["note"]["back"]


def test_long_media_name_fits_anki_limit(tmp_path: Path):
    image = tmp_path / ("3Blue1Brown - The more general uncertainty principle, regarding Fourier transforms-1785634799134.png")
    image.write_bytes(b"png")
    built = job(back_media_files=[str(image)])
    name = built["note"]["media"][0]["filename"]
    assert len(name) <= 100
    assert name.startswith("anki_cli_") and name.endswith(".png")


def test_existing_notetype_receives_current_styling(tmp_path: Path):
    path = tmp_path / "collection.anki2"
    Collection(str(path)).close()
    client = HeadlessClient(path)
    try:
        upsert_job(client, job())
        client.update_model_styling("AnkiCLI-Basic-v1", ".card{color:#111}", "{{Front}}", "{{Back}}")
        schema_mark = client.col.db.scalar("select scm from col")
        upsert_job(client, job(front="두 번째"))
        styling = client.model_styling("AnkiCLI-Basic-v1")
        assert styling["css"] == MODEL_CSS
        assert "{{FrontSide}}" in styling["back"]
        assert client.col.db.scalar("select scm from col") == schema_mark
    finally:
        client.close()
