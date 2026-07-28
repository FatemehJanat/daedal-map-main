"""Project source-owned metric caveats into executable display orders."""

from __future__ import annotations


def collect_metric_caveats(items: list[dict], *, load_source_metadata_func) -> list[str]:
    """Return deduplicated required framing for metrics actually selected.

    The caveat belongs to the source contract, not to the model's prose.  It is
    attached only after an order is validated, so an unrelated metric does not
    produce a warning merely because its column exists in the source.
    """
    caveats: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("_valid"):
            continue
        source_id = str(item.get("source_id") or "").strip()
        metric_id = str(item.get("metric") or "").strip()
        if not source_id or not metric_id:
            continue
        metadata = load_source_metadata_func(source_id) or {}
        metric = (metadata.get("metrics") or {}).get(metric_id) or {}
        semantics = metric.get("response_semantics") if isinstance(metric, dict) else {}
        framing = str((semantics or {}).get("required_framing") or "").strip()
        if not framing:
            continue
        item["source_caveats"] = list(dict.fromkeys([*(item.get("source_caveats") or []), framing]))
        if framing not in caveats:
            caveats.append(framing)
    return caveats


def append_source_caveats(summary: str | None, caveats: list[str]) -> str | None:
    """Append source-owned caveats once to the user-visible execution summary."""
    text = str(summary or "").strip()
    for caveat in caveats:
        if caveat.lower() not in text.lower():
            text = f"{text} {caveat}".strip()
    return text or None
