"""Pure helpers for LanceDB row scoring and candidate dicts (testable, UI-agnostic)."""

from __future__ import annotations

import pandas as pd


def row_vector_distance(row) -> float | None:
    """LanceDB adds `_distance` for vector search (cosine: 0 = identical, 2 = opposite)."""
    try:
        if hasattr(row, "index") and "_distance" in row.index:
            v = row["_distance"]
        elif isinstance(row, dict):
            v = row.get("_distance")
        else:
            return None
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return float(v)
    except (KeyError, TypeError, ValueError):
        return None


def format_match_line(d: float) -> str:
    """Map cosine distance to a simple %-style label (rough, for UX only)."""
    d = float(d)
    sim = max(0.0, min(1.0, 1.0 - d / 2.0))
    pct = round(sim * 100, 1)
    return f"Semantic match ~{pct}% · cosine distance {d:.3f} (lower is closer)"


def candidate_from_lancedb_row(row) -> dict:
    meta = row.get("meta") if hasattr(row, "get") else None
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        try:
            meta = dict(meta)
        except Exception:
            meta = {}
    d = row_vector_distance(row)
    return {
        "name": meta.get("name", ""),
        "headline": meta.get("headline", ""),
        "linkedin": meta.get("linkedin", ""),
        "_vector_distance": d,
        "_provenance": "lancedb_search",
    }


def build_search_digest_body(df: pd.DataFrame, query: str) -> str:
    lines = [
        "Agent Carter — saved candidate list",
        f"Query: {query}",
        "",
    ]
    for _, row in df.iterrows():
        meta = row.get("meta") or {}
        name = meta.get("name", "")
        headline = meta.get("headline", "")
        linkedin = meta.get("linkedin", "")
        lines.append(name)
        if headline and str(headline) not in ("None",):
            lines.append(f"  {headline}")
        if linkedin:
            lines.append(f"  {linkedin}")
        dist = row_vector_distance(row)
        if dist is not None:
            lines.append(f"  {format_match_line(dist)}")
        lines.append("")
    return "\n".join(lines).strip()
