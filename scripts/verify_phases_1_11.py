from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("phase_test_manifest.json")

SUMMARY_PATTERNS = {
    "passed": re.compile(r"(?:^|\s)(\d+) passed(?:,|\s|$)"),
    "failed": re.compile(r"(?:^|\s)(\d+) failed(?:,|\s|$)"),
    "skipped": re.compile(r"(?:^|\s)(\d+) skipped(?:,|\s|$)"),
    "errors": re.compile(r"(?:^|\s)(\d+) error(?:s)?(?:,|\s|$)"),
}


def parse_counts(text: str) -> dict[str, int]:
    counts = {k: 0 for k in SUMMARY_PATTERNS}
    for key, pattern in SUMMARY_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            counts[key] = int(matches[-1])
    return counts


def run_command(cmd: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    text = proc.stdout or ""
    log_path.write_text(text, encoding="utf-8")
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "counts": parse_counts(text),
        "log": str(log_path),
        "tail": "\n".join(text.splitlines()[-25:]),
    }


def phase_targets(manifest: dict[str, Any], phase: int, mode: str) -> list[str]:
    return list(manifest[str(phase)][mode])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase-by-phase verification harness for GraphHacks Phases 1-11."
    )
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke",
                        help="smoke runs representative live tests; full runs every test file assigned to each phase")
    parser.add_argument("--from-phase", type=int, default=1)
    parser.add_argument("--to-phase", type=int, default=11)
    parser.add_argument("--allow-skips", action="store_true",
                        help="do not fail a phase solely because pytest skipped integration tests")
    parser.add_argument("--with-browser", action="store_true",
                        help="after pytest verification, run Phase 10 and Phase 11 isolated browser/API acceptance scripts")
    parser.add_argument("--pytest-extra", nargs="*", default=[],
                        help="extra arguments appended to every pytest invocation")
    args = parser.parse_args()

    if not (1 <= args.from_phase <= args.to_phase <= 11):
        parser.error("phase range must satisfy 1 <= from <= to <= 11")

    if not MANIFEST_PATH.exists():
        print(f"Manifest not found: {MANIFEST_PATH}")
        return 2
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / f"phase1_11_verification_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "mode": args.mode,
        "root": str(ROOT),
        "started_at": datetime.now().isoformat(),
        "phase_range": [args.from_phase, args.to_phase],
        "strict_skips": not args.allow_skips,
        "phases": {},
        "browser_acceptance": {},
    }

    overall_ok = True
    totals = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}

    print("=" * 78)
    print("GraphHacks Phases 1-11 verification")
    print(f"Repository : {ROOT}")
    print(f"Mode       : {args.mode}")
    print(f"Phases     : {args.from_phase}..{args.to_phase}")
    print(f"FalkorDB   : {os.getenv('FALKORDB_HOST','localhost')}:{os.getenv('FALKORDB_PORT','6379')}")
    print("NOTE: pytest integration fixtures use isolated temporary graph names.")
    print("=" * 78)

    for phase in range(args.from_phase, args.to_phase + 1):
        info = manifest[str(phase)]
        targets = phase_targets(manifest, phase, args.mode)
        print(f"\n--- PHASE {phase}: {info['name']} ---")
        cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", *targets, *args.pytest_extra]
        result = run_command(cmd, ROOT, out_dir / f"phase_{phase:02d}.log")
        counts = result["counts"]
        for key in totals:
            totals[key] += counts[key]
        phase_ok = result["returncode"] == 0
        if not args.allow_skips and counts["skipped"] > 0:
            phase_ok = False
        report["phases"][str(phase)] = {
            "name": info["name"],
            "targets": targets,
            "ok": phase_ok,
            **result,
        }
        overall_ok = overall_ok and phase_ok
        status = "PASS" if phase_ok else "FAIL"
        print(f"[{status}] Phase {phase}: passed={counts['passed']} failed={counts['failed']} skipped={counts['skipped']} errors={counts['errors']}")
        if not phase_ok:
            print(result["tail"])

    if args.with_browser:
        for phase, script in ((10, "verify_phase10_browser.py"), (11, "verify_phase11_api.py")):
            if phase < args.from_phase or phase > args.to_phase:
                continue
            script_path = ROOT / "scripts" / script
            print(f"\n--- PHASE {phase} LIVE ACCEPTANCE: {script} ---")
            if not script_path.exists():
                result = {
                    "returncode": 2,
                    "counts": {"passed": 0, "failed": 0, "skipped": 0, "errors": 1},
                    "log": None,
                    "tail": f"Missing script: {script_path}",
                    "command": [sys.executable, str(script_path)],
                }
            else:
                result = run_command(
                    [sys.executable, str(script_path)],
                    ROOT,
                    out_dir / f"phase_{phase:02d}_browser.log",
                )
            ok = result["returncode"] == 0
            report["browser_acceptance"][str(phase)] = {"ok": ok, **result}
            overall_ok = overall_ok and ok
            print(f"[{'PASS' if ok else 'FAIL'}] Phase {phase} live acceptance")
            if not ok:
                print(result["tail"])

    report["totals"] = totals
    report["passed"] = overall_ok
    report["finished_at"] = datetime.now().isoformat()
    report_path = out_dir / "phase1_11_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print("FINAL PHASE 1-11 VERIFICATION")
    for phase in range(args.from_phase, args.to_phase + 1):
        item = report["phases"][str(phase)]
        print(f"Phase {phase:>2}: {'PASS' if item['ok'] else 'FAIL'}")
    if args.with_browser:
        for p in sorted(report["browser_acceptance"], key=int):
            print(f"Phase {p:>2} browser/API acceptance: {'PASS' if report['browser_acceptance'][p]['ok'] else 'FAIL'}")
    print(f"pytest totals: {totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped, {totals['errors']} errors")
    print(f"Report      : {report_path}")
    print(f"Logs        : {out_dir}")
    print(f"RESULT      : {'PASS' if overall_ok else 'FAIL'}")
    print("=" * 78)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
