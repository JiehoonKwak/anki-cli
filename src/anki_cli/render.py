from __future__ import annotations

import html
import re

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


MATH_RE = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", re.DOTALL)
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ESCAPE_EATEN_TEX_COMMAND_RE = re.compile(r"\t|\n(?:ight|abla|eq|u\b|ewline|ot|ormalsize|ho\b)")


class FieldTextError(ValueError):
    """Raised when card text was corrupted before it reached the CLI."""


def check_field_text(name: str, value: str) -> None:
    """Reject text whose backslash escapes (\\r in \\right, \\n in \\nabla, \\t in
    \\theta) were interpreted by the writer, which breaks MathJax on every device."""
    match = CONTROL_CHARACTER_RE.search(value)
    if match:
        raise FieldTextError(
            f"{name} contains control character {match.group()!r} near {value[max(0, match.start() - 20):match.end() + 10]!r}; "
            "a backslash escape such as \\r in \\right or \\f in \\frac was interpreted while writing the text"
        )
    for math in MATH_RE.finditer(value):
        eaten = ESCAPE_EATEN_TEX_COMMAND_RE.search(math.group())
        if eaten:
            raise FieldTextError(
                f"{name} math {math.group()!r} has a line break where a TeX command should be; "
                "a backslash escape such as \\n in \\nabla or \\r in \\right was interpreted while writing the text"
            )


def _set_aside_math_from_markdown_escapes(value: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def keep(match: re.Match[str]) -> str:
        spans.append(match.group())
        return f"ANKICLIMATH{len(spans) - 1}X"

    return MATH_RE.sub(keep, value), spans


def render_field(value: str, mode: str) -> str:
    if mode == "plain":
        return html.escape(value).replace("\n", "<br>\n")
    if mode == "markdown-safe":
        protected, spans = _set_aside_math_from_markdown_escapes(value)
        md = MarkdownIt("commonmark", {"breaks": True, "html": False})
        rendered = nh3.clean(
            md.render(protected),
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes=ALLOWED_URL_SCHEMES,
        )
        for index, span in enumerate(spans):
            rendered = rendered.replace(f"ANKICLIMATH{index}X", html.escape(span, quote=False))
        return rendered
    if mode == "html":
        return value
    raise ValueError(f"unsupported render_mode: {mode}")
