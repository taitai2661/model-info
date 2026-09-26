"""Collectors whose source is a public documentation page served as Markdown.

Groq, Together AI and Fireworks publish their model catalogues as Markdown
documentation rather than as a JSON API, and their endpoints answer 401 without
a key. These collectors fetch the page itself (no credential involved) and read
the tables from it, which keeps the "no API key in the repository" rule intact.

Helpers here only interpret Markdown; what a cell means (which column is the
context window, which one is the output price) stays in each collector.
"""
from __future__ import annotations

import re

import httpx

from .base import BaseCollector, CollectorError

# Prices that are not billed per token ("$0.111 per hour", "$40.00 per 1M
# characters") must never land in a 1M_tokens pricing block.
NON_TOKEN_UNIT_RE = re.compile(
    r"per\s+(?:hour|minute|second|image|character|1k\s+characters|1m\s+characters)",
    re.IGNORECASE,
)
MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


def strip_markdown(cell: str) -> str:
    """Drop images, links, code marks and escapes from a table cell."""
    out = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", cell or "")
    out = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", out)
    out = out.replace("\\", "")
    out = re.sub(r"`([^`]*)`", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def link_targets(cell: str) -> list[str]:
    """Every ``[label](target)`` destination inside a cell, in document order."""
    return re.findall(r"\]\(([^)]+)\)", cell or "")


def split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        cell == "" or SEPARATOR_CELL_RE.match(cell.replace(" ", "")) for cell in cells
    )


def parse_tables(text: str) -> list[dict]:
    """Parse GitHub-flavoured pipe tables into ``{"header": [...], "rows": [...]}``.

    A block of consecutive ``|`` lines whose second line is a separator row is a
    table; anything else (paragraphs, notes) ends the block.
    """
    tables: list[dict] = []
    block: list[str] = []

    def flush() -> None:
        if len(block) >= 2:
            header = split_row(block[0])
            if is_separator(split_row(block[1])):
                rows = [split_row(line) for line in block[2:]]
                tables.append({"header": header,
                               "rows": [r for r in rows if any(r)]})
        block.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            block.append(line)
        else:
            flush()
    flush()
    return tables


def column_index(header: list[str], *candidates: str) -> int | None:
    """Index of the first header cell whose plain text matches a candidate."""
    wanted = {c.lower() for c in candidates}
    for i, cell in enumerate(header):
        if strip_markdown(cell).lower() in wanted:
            return i
    return None


def money_values(cell: str) -> list[float]:
    """Dollar amounts in a price cell; empty when the unit is not per token."""
    text = strip_markdown(cell)
    if NON_TOKEN_UNIT_RE.search(text):
        return []
    values = [float(v.replace(",", "")) for v in MONEY_RE.findall(text)]
    if not values and re.search(r"\bfree\b", text, re.IGNORECASE):
        values = [0.0]
    return values


def parse_int(cell: str) -> int | None:
    """A whole number in a cell (``131,072``); ``-`` and dashes mean unknown."""
    text = strip_markdown(cell).replace(",", "")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


class DocsCollector(BaseCollector):
    """Collector that reads a Markdown documentation page instead of an API.

    ``api_url`` points at the page (a ``.md`` URL or any endpoint that serves
    Markdown); ``normalize`` receives the raw text and returns the usual
    ``{"provider_models": ...}`` payload.
    """

    env_var = None
    accept = "text/markdown, text/plain;q=0.9, */*;q=0.8"

    def fetch(self) -> str:
        headers = {"User-Agent": "model-info-collector/1.0", "Accept": self.accept}
        try:
            response = httpx.get(self.api_url, headers=headers, timeout=30,
                                 follow_redirects=True)
        except httpx.HTTPError as exc:
            raise CollectorError(f"{self.name}: request failed: {exc}") from exc
        if response.status_code >= 400:
            raise CollectorError(
                f"{self.name}: HTTP {response.status_code} from {self.api_url}: "
                f"{response.text[:200]}"
            )
        text = response.text
        if text.lstrip()[:64].lower().startswith(("<!doctype html", "<html")):
            raise CollectorError(
                f"{self.name}: {self.api_url} returned HTML instead of Markdown; "
                "the documentation layout may have changed"
            )
        return text
