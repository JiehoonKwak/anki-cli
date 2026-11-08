"""How an AnkiCLI note looks: notetype fields, templates, styling, media and preview HTML."""

from __future__ import annotations

import html
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from .backend import AnkiClient
from .render import render_field


NOTETYPE_FIELDS = [
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
FRONT_TEMPLATE = "{{Front}}"
BACK_TEMPLATE = """{{FrontSide}}
<hr id="answer">
{{Back}}
{{#Extra}}
<hr>
<div class="extra">{{Extra}}</div>
{{/Extra}}"""
MODEL_CSS = files(__package__).joinpath("card.css").read_text(encoding="utf-8")


def ensure_notetype(client: AnkiClient, notetype: str) -> None:
    model_names = client.model_names()
    if notetype not in model_names:
        client.create_model(notetype, NOTETYPE_FIELDS, FRONT_TEMPLATE, BACK_TEMPLATE, MODEL_CSS)
        return
    fields = client.model_field_names(notetype)
    if fields != NOTETYPE_FIELDS:
        raise RuntimeError(f"notetype {notetype} field mismatch: expected {NOTETYPE_FIELDS}, got {fields}")
    wanted = {"css": MODEL_CSS, "front": FRONT_TEMPLATE, "back": BACK_TEMPLATE}
    if client.model_styling(notetype) != wanted:
        client.update_model_styling(notetype, MODEL_CSS, FRONT_TEMPLATE, BACK_TEMPLATE)


def media_metadata(media_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    keys = (
        "field",
        "filename",
        "original_name",
        "sha256",
        "kind",
        "caption",
        "source_uri",
        "source_locator",
        "alt",
        "selection_reason",
    )
    return [{key: str(item[key]) for key in keys if item.get(key)} for item in media_items]


def render_media(media: dict[str, Any]) -> str:
    kind = html.escape(str(media.get("kind", "other")), quote=True)
    alt = html.escape(str(media.get("alt") or media.get("original_name") or media["filename"]), quote=True)
    img = f'<img src="{html.escape(media["filename"], quote=True)}" alt="{alt}">'
    caption = str(media.get("caption") or "")
    source_uri = str(media.get("source_uri") or "")
    source_locator = str(media.get("source_locator") or "")
    if caption:
        caption_html = html.escape(caption)
        if source_uri and source_locator:
            source_html = (
                '<span class="media-source">'
                f'<a href="{html.escape(source_uri, quote=True)}">{html.escape(source_locator)}</a>'
                "</span>"
            )
        elif source_uri:
            source_html = (
                '<span class="media-source">'
                f'<a href="{html.escape(source_uri, quote=True)}">{html.escape(source_uri)}</a>'
                "</span>"
            )
        elif source_locator:
            source_html = f'<span class="media-source">{html.escape(source_locator)}</span>'
        else:
            source_html = ""
        return f'<figure class="media media-kind-{kind}">{img}<figcaption>{caption_html}{source_html}</figcaption></figure>'
    return f'<div class="media media-kind-{kind}">{img}</div>'


def render_preview_media(media: dict[str, Any]) -> str:
    preview_media = dict(media)
    preview_media["filename"] = Path(str(media["path"])).resolve().as_uri()
    rendered = render_media(preview_media)
    reason = str(media.get("selection_reason") or "")
    if reason:
        rendered += f'<p class="selection-reason">{html.escape(reason)}</p>'
    return rendered


def render_preview_html(job: dict[str, Any]) -> str:
    note = job["note"]
    mode = note.get("render_mode", "markdown-safe")
    front_media = [media for media in note.get("media", []) if media.get("field") == "front"]
    back_media = [media for media in note.get("media", []) if media.get("field") == "back"]
    tags = " ".join(note.get("tags", []))
    source_title = note.get("source_title", "")
    source_uri = note.get("source_uri", "")
    source_locator = note.get("source_locator", "")
    media_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(media.get('field', '')))}</td>"
        f"<td>{html.escape(str(media.get('kind', 'other')))}</td>"
        f"<td>{html.escape(str(media.get('original_name', '')))}</td>"
        f"<td>{html.escape(str(media.get('source_locator', '')))}</td>"
        f"<td>{html.escape(str(media.get('caption', '')))}</td>"
        "</tr>"
        for media in note.get("media", [])
    )
    front = render_field(note["front"], mode) + "".join(render_preview_media(media) for media in front_media)
    back = render_field(note["back"], mode) + "".join(render_preview_media(media) for media in back_media)
    card = f'{front}<hr id="answer">{back}'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Anki card preview</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif; margin: 24px; line-height: 1.5; color: #111; background: #eef0f3; }}
    .meta {{ max-width: 780px; font-size: 14px; }}
    .phones {{ display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; margin: 20px 0; }}
    .phone {{ width: 375px; max-width: 100%; box-sizing: border-box; padding: 20px 16px; border-radius: 24px; border: 1px solid #c9ccd3; background: #fff; }}
    .phone.night {{ background: #1c1c1e; border-color: #3a3c43; }}
    .phone-label {{ font: 12px ui-monospace, Menlo, monospace; color: #555; margin-bottom: 6px; }}
    .selection-reason {{ color: #555; font-size: 0.85em; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 780px; margin-top: 12px; font-size: 14px; }}
    td, th {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; vertical-align: top; }}
    /* AnkiCLI-Basic-v1 notetype CSS, identical to what drain applies */
{MODEL_CSS}
  </style>
  <script>window.MathJax = {{ tex: {{ inlineMath: [["\\\\(", "\\\\)"]], displayMath: [["\\\\[", "\\\\]"]] }}, chtml: {{ displayAlign: "left" }} }};</script>
  <script async src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml.js"></script>
</head>
<body>
  <div class="meta">
    <p><strong>Deck:</strong> {html.escape(job["target"]["deck"])} &middot; <strong>ExternalID:</strong> {html.escape(note["external_id"])}</p>
    <p><strong>Tags:</strong> {html.escape(tags)}</p>
    <p><strong>Source:</strong> {html.escape(source_title)} {html.escape(source_uri)} {html.escape(source_locator)}</p>
  </div>
  <div class="phones">
    <div><div class="phone-label">375px &middot; day</div><div class="phone"><div class="card">{card}</div></div></div>
    <div><div class="phone-label">375px &middot; night mode</div><div class="phone night"><div class="card nightMode">{card}</div></div></div>
  </div>
  <table>
    <thead><tr><th>Side</th><th>Kind</th><th>File</th><th>Locator</th><th>Caption</th></tr></thead>
    <tbody>{media_rows}</tbody>
  </table>
</body>
</html>
"""


def rendered_fields(job: dict[str, Any]) -> dict[str, str]:
    note = job["note"]
    mode = note.get("render_mode", "markdown-safe")
    meta = {
        **note.get("metadata", {}),
        "job_id": job["job_id"],
        "created_at": job.get("created_at"),
        "created_by": job.get("created_by", {}),
        "render_mode": mode,
        "media": media_metadata(note.get("media", [])),
    }
    front = render_field(note["front"], mode)
    back = render_field(note["back"], mode)
    for media in note.get("media", []):
        img = render_media(media)
        if media.get("field") == "front":
            front += img
        elif media.get("field") == "back":
            back += img
    return {
        "ExternalID": note["external_id"],
        "Front": front,
        "Back": back,
        "Extra": render_field(note.get("extra", ""), mode) if note.get("extra") else "",
        "SourceTitle": html.escape(note.get("source_title", "")),
        "SourceURI": html.escape(note.get("source_uri", "")),
        "SourceLocator": html.escape(note.get("source_locator", "")),
        "SourceHash": html.escape(note.get("source_hash", "")),
        "MetaJSON": html.escape(json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
    }
