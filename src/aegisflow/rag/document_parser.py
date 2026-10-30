"""Parse supported local document formats into stable plain text."""

import re
from html.parser import HTMLParser

_HTML_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


class _HTMLTextExtractor(HTMLParser):
    """Collect visible HTML text while preserving block boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif self.ignored_depth == 0 and tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif self.ignored_depth == 0 and tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_depth == 0:
            self.parts.append(data)


def clean_text(text: str) -> str:
    """Normalize line endings and insignificant trailing whitespace."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in normalized.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return cleaned


def parse_document(text: str, suffix: str) -> str:
    """Return cleaned text for Markdown, HTML, and plain-text inputs."""
    if suffix.lower() in {".html", ".htm"}:
        extractor = _HTMLTextExtractor()
        extractor.feed(text)
        extractor.close()
        text = "".join(extractor.parts)
    return clean_text(text)
