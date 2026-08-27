"""Block constructors for the chat response.

Both the deterministic fallback and the real LLM providers emit the same
`{text, blocks}` contract. The frontend (`web/js/blocks.js`) renders each
block. Keep field names in sync with that renderer.

Block types
-----------
text : {"type":"text","markdown": "..."}
kpi  : {"type":"kpi","items":[{"label","value","delta?","tone?"}]}
chart: {"type":"chart","title","chart_type":"line|bar|donut","categories":[],
        "series":[{"name","data":[],"color?","area?","dashed?"}],"horizontal?","unit?"}
table: {"type":"table","title?","columns":[{"key","label"}],"rows":[{...}]}
map  : {"type":"map","title?","center":[lat,lng],"zoom?",
        "points":[{"lat","lng","weight?","label?","color?"}]}
note : {"type":"note","text":"..."}   # small muted caption
"""
from __future__ import annotations

from typing import Any


def text(markdown: str) -> dict:
    return {"type": "text", "markdown": markdown}


def note(text_: str) -> dict:
    return {"type": "note", "text": text_}


def kpi(items: list[dict]) -> dict:
    return {"type": "kpi", "items": items}


def chart(title: str, chart_type: str, categories: list, series: list,
          horizontal: bool = False, unit: str | None = None) -> dict:
    return {"type": "chart", "title": title, "chart_type": chart_type,
            "categories": categories, "series": series,
            "horizontal": horizontal, "unit": unit}


def table(title: str | None, columns: list[dict], rows: list[dict]) -> dict:
    return {"type": "table", "title": title, "columns": columns, "rows": rows}


def map_block(title: str | None, center: list[float], points: list[dict],
              zoom: int = 11) -> dict:
    return {"type": "map", "title": title, "center": center, "zoom": zoom,
            "points": points}


def response(text_: str, blocks: list[dict] | None = None) -> dict:
    return {"text": text_, "blocks": blocks or []}
