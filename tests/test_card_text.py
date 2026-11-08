from __future__ import annotations

from html.parser import HTMLParser
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


def test_markdown_safe_math_respects_markdown_structure():
    assert render_field("Use `\\(` and `\\)` here", "markdown-safe") == "<p>Use <code>\\(</code> and <code>\\)</code> here</p>\n"
    linked = render_field("[\\(x\\)]: https://example.com\n\n[\\(x\\)]", "markdown-safe")
    assert '<a href="https://example.com"' in linked and "\\(x\\)" in linked
    assert "\\(\\text{ANKICLIMATH1X}\\) then \\(y\\)" in render_field("\\(\\text{ANKICLIMATH1X}\\) then \\(y\\)", "markdown-safe")
    assert "\\(a_1 * b_1 * c\\)" in render_field("\\(a_1 * b_1 * c\\)", "markdown-safe")


def test_markdown_safe_math_cannot_inject_attributes():
    rendered = render_field('[tap](https://example.com "\\(x" onclick="alert(1)//\\)")', "markdown-safe")
    attributes: list[str] = []

    class Collect(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attributes.extend(name for name, _ in attrs)

    Collect().feed(rendered)
    assert "onclick" not in attributes


def test_escape_eaten_by_writer_is_rejected():
    with pytest.raises(SchemaError, match="control character"):
        job(back="<div>\\[\\left(\\frac{E}{c}\right)^2\\]</div>")
    with pytest.raises(SchemaError, match="TeX command"):
        job(back="<div>\\[\\left(\\frac{E}{c}\night)^2\\]</div>")
    with pytest.raises(SchemaError, match="TeX command"):
        job(front="\\(\theta\\)")


def test_multiline_display_math_is_accepted():
    for body in ("\\[\na^2 + b^2\n= c^2\n\\]", "\\[\nu = v + w\n\\]", "\\[\neq = a + b\n\\]", "\\[\n\tx = 1\n\\]"):
        built = job(back=f"<div>{body}</div>")
        assert body in built["note"]["back"]


def test_long_media_name_fits_anki_limit(tmp_path: Path):
    image = tmp_path / ("3Blue1Brown - The more general uncertainty principle, regarding Fourier transforms-1785634799134.png")
    image.write_bytes(b"png")
    built = job(back_media_files=[str(image)])
    name = built["note"]["media"][0]["filename"]
    assert len(name) <= 100
    assert name.startswith("anki_cli_") and name.endswith(".png")
    odd = tmp_path / ("image." + "a" * 120)
    odd.write_bytes(b"x")
    assert len(job(back_media_files=[str(odd)])["note"]["media"][0]["filename"]) <= 100


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


def test_custom_notetype_keeps_its_templates(tmp_path: Path):
    path = tmp_path / "collection.anki2"
    Collection(str(path)).close()
    client = HeadlessClient(path)
    try:
        upsert_job(client, job())
        model = client.col.models.copy(client.col.models.by_name("AnkiCLI-Basic-v1"))
        model["name"] = "Custom"
        client.col.models.update_dict(model)
        client.update_model_styling("Custom", ".x{}", "{{Front}} {{SourceTitle}}", "{{Back}}")
        custom = build_upsert_job(deck="Deck", front="q", back="a", render_mode="html", agent="test", notetype="Custom")
        upsert_job(client, custom)
        assert client.model_styling("Custom") == {"css": ".x{}", "front": "{{Front}} {{SourceTitle}}", "back": "{{Back}}"}
    finally:
        client.close()
