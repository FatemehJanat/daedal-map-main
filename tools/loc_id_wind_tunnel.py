from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mapmover.runtime.loc_id_identity_doctrine import (
    DOCTRINE_PROFILES,
    compare_doctrine_cases,
    doctrine_decisions,
    evaluate_dual_mode_cases,
    evaluate_identity_cases,
)

DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "loc_id_wind_tunnel_samples.json"


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
        "| Signal | Case | System | Role | Scope | Level | Placement | Issues | Design questions |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        issues = "<br>".join(result.get("issues") or []) or "-"
        questions = "<br>".join(result.get("design_questions") or []) or "-"
        lines.append(
            "| {signal} | {case} | {system} | {role} | {scope} | {level} | {placement} | {issues} | {questions} |".format(
                signal=result.get("signal"),
                case=result.get("case"),
                system=result.get("source_system") or "-",
                role=result.get("role"),
                scope=result.get("first_segment_scope"),
                level=result.get("reference_level") or "-",
                placement=result.get("placement_semantics") or "-",
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
            "| {signal} | {case} | {system} | {declared_role}/{declared_scope}/{declared_level}/{declared_placement} | {raw_role}/{raw_scope}/{raw_level}/{raw_placement} | {deltas} |".format(
                signal=result.get("signal"),
                case=result.get("case"),
                system=result.get("source_system") or "-",
                declared_role=declared.get("role"),
                declared_scope=declared.get("first_segment_scope"),
                declared_level=declared.get("reference_level") or "-",
                declared_placement=declared.get("placement_semantics") or "-",
                raw_role=raw.get("role"),
                raw_scope=raw.get("first_segment_scope"),
                raw_level=raw.get("reference_level") or "-",
                raw_placement=raw.get("placement_semantics") or "-",
                deltas=deltas,
            )
        )
    return "\n".join(lines) + "\n"


def _render_compare_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# loc_id Wind Tunnel Doctrine Comparison",
        "",
        "| Signal | Case | System | Deltas |",
        "|---|---|---|---|",
    ]
    for result in results:
        deltas = "<br>".join(result.get("deltas") or []) or "-"
        lines.append(
            "| {signal} | {case} | {system} | {deltas} |".format(
                signal=result.get("signal"),
                case=result.get("case"),
                system=result.get("source_system") or "-",
                deltas=deltas,
            )
        )
    return "\n".join(lines) + "\n"


def _render_matrix_markdown(cases: list[dict[str, Any]]) -> str:
    doctrines = tuple(DOCTRINE_PROFILES)
    lines = [
        "# loc_id Wind Tunnel Doctrine Matrix",
        "",
        f"Shared fixture cases: {len(cases)}",
        "",
        "| Doctrine | pass | expected_issue | unexpected_issue | raw_declared_delta | needs_policy_decision | doctrine_conflict | missing_expected_issue |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    signal_order = (
        "pass",
        "expected_issue",
        "unexpected_issue",
        "raw_declared_delta",
        "needs_policy_decision",
        "doctrine_conflict",
        "missing_expected_issue",
    )
    for doctrine in doctrines:
        results = evaluate_dual_mode_cases(cases, doctrine=doctrine)
        counts = Counter(str(result.get("signal")) for result in results)
        lines.append(
            "| {doctrine} | {counts} |".format(
                doctrine=doctrine,
                counts=" | ".join(str(counts.get(signal, 0)) for signal in signal_order),
            )
        )

    lines.extend(
        [
            "",
            "| Left | Right | pass | doctrine_delta | needs_policy_decision |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for left, right in zip(doctrines, doctrines[1:]):
        compared = compare_doctrine_cases(cases, left=left, right=right)
        counts = Counter(str(result.get("signal")) for result in compared)
        lines.append(
            "| {left} | {right} | {passed} | {delta} | {decision} |".format(
                left=left,
                right=right,
                passed=counts.get("pass", 0),
                delta=counts.get("doctrine_delta", 0),
                decision=counts.get("needs_policy_decision", 0),
            )
        )
    return "\n".join(lines) + "\n"


def _render_decisions_markdown() -> str:
    lines = [
        "# loc_id Doctrine Decisions",
        "",
        "| Doctrine | Decision ID | Decision | Effect |",
        "|---|---|---|---|",
    ]
    for doctrine in DOCTRINE_PROFILES:
        decisions = doctrine_decisions(doctrine)
        if not decisions:
            lines.append(f"| {doctrine} | - | - | - |")
        for decision in decisions:
            lines.append(
                "| {doctrine} | {id} | {decision} | {effect} |".format(
                    doctrine=doctrine,
                    id=decision.get("id") or "-",
                    decision=decision.get("decision") or "-",
                    effect=decision.get("effect") or "-",
                )
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate sampled geography identifiers against loc_id doctrine.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--mode", choices=("single", "dual", "compare", "matrix", "decisions"), default="single")
    doctrine_choices = tuple(DOCTRINE_PROFILES)
    parser.add_argument("--doctrine", choices=doctrine_choices, default="proposed_changes")
    parser.add_argument("--left-doctrine", choices=doctrine_choices, default="present_system")
    parser.add_argument("--right-doctrine", choices=doctrine_choices, default="proposed_changes")
    parser.add_argument("--fail-on-unexpected", action="store_true")
    args = parser.parse_args()

    cases = _load_cases(args.fixture)
    if args.mode in {"matrix", "decisions"}:
        results = []
    elif args.mode == "compare":
        results = compare_doctrine_cases(cases, left=args.left_doctrine, right=args.right_doctrine)
    elif args.mode == "dual":
        results = evaluate_dual_mode_cases(cases, doctrine=args.doctrine)
    else:
        results = evaluate_identity_cases(cases, doctrine=args.doctrine)
    if args.mode == "decisions":
        if args.format == "json":
            payload = {
                doctrine: doctrine_decisions(doctrine)
                for doctrine in DOCTRINE_PROFILES
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(_render_decisions_markdown(), end="")
    elif args.mode == "matrix":
        if args.format == "json":
            payload = {
                doctrine: evaluate_dual_mode_cases(cases, doctrine=doctrine)
                for doctrine in DOCTRINE_PROFILES
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(_render_matrix_markdown(cases), end="")
    elif args.format == "json":
        print(json.dumps(results, indent=2, sort_keys=True))
    elif args.mode == "compare":
        print(_render_compare_markdown(results), end="")
    elif args.mode == "dual":
        print(_render_dual_markdown(results), end="")
    else:
        print(_render_markdown(results), end="")

    if args.fail_on_unexpected and any(not result.get("ok") for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
