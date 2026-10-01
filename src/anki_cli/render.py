from __future__ import annotations

import html

from markdown_it import MarkdownIt
import nh3


ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "code": {"class"},
    "span": {"class"},
    "div": {"class"},
}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "file"}


def render_field(value: str, mode: str) -> str:
    if mode == "plain":
        return html.escape(value).replace("\n", "<br>\n")
    if mode == "markdown-safe":
        md = MarkdownIt("commonmark", {"breaks": True, "html": False})
        rendered = md.render(value)
        return nh3.clean(
            rendered,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes=ALLOWED_URL_SCHEMES,
        )
    if mode == "html":
        return value
    raise ValueError(f"unsupported render_mode: {mode}")
