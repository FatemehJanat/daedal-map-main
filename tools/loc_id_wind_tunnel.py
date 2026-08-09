from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mapmover.runtime.loc_id_identity_doctrine import evaluate_dual_mode_cases, evaluate_identity_cases

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "loc_id_wind_tunnel_samples.json"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON list")
    return payload


def _render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# loc_id Wind Tunnel Report",
        "",
        "| Signal | Case | System | Role | Scope | Issues | Design questions |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        issues = "<br>".join(result.get("issues") or []) or "-"
        questions = "<br>".join(result.get("design_questions") or []) or "-"
        lines.append(
            "| {signal} | {case} | {system} | {role} | {scope} | {issues} | {questions} |".format(
                signal=result.get("signal"),
                case=result.get("case"),
                system=result.get("source_system") or "-",
                role=result.get("role"),
                scope=result.get("first_segment_scope"),
                issues=issues,
                questions=questions,
            )
        )
    return "\n".join(lines) + "\n"


def _render_dual_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# loc_id Wind Tunnel Raw/Declared Report",
        "",
        "| Signal | Case | System | Declared | Raw | Deltas |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        declared = result.get("declared") or {}
        raw = result.get("raw") or {}
        deltas = "<br>".join(result.get("deltas") or []) or "-"
        lines.append(
            "| {signal} | {case} | {system} | {declared_role}/{declared_scope} | {raw_role}/{raw_scope} | {deltas} |".format(
                signal=result.get("signal"),
                case=result.get("case"),
                system=result.get("source_system") or "-",
                declared_role=declared.get("role"),
                declared_scope=declared.get("first_segment_scope"),
                raw_role=raw.get("role"),
                raw_scope=raw.get("first_segment_scope"),
                deltas=deltas,
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate sampled geography identifiers against loc_id doctrine.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--mode", choices=("single", "dual"), default="single")
    parser.add_argument("--fail-on-unexpected", action="store_true")
    args = parser.parse_args()

    cases = _load_cases(args.fixture)
    results = evaluate_dual_mode_cases(cases) if args.mode == "dual" else evaluate_identity_cases(cases)
    if args.format == "json":
        print(json.dumps(results, indent=2, sort_keys=True))
    elif args.mode == "dual":
        print(_render_dual_markdown(results), end="")
    else:
        print(_render_markdown(results), end="")

    if args.fail_on_unexpected and any(not result.get("ok") for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
