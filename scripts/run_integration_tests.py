"""Run GraphHacks Components 1–6 and live FalkorDB integration tests.

Examples (from repository root):
  python scripts/run_integration_tests.py --suite components
  python scripts/run_integration_tests.py --suite database
  python scripts/run_integration_tests.py --suite all
  python scripts/run_integration_tests.py --check

Database suite requires a reachable FalkorDB and Python dependencies. Integration
fixtures use temporary graph names; this launcher never seeds or clears your
normal company graph. A skipped database suite is NOT counted as a pass.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = [
    'test_agent_runtime_step1.py',
    'test_supervisor_component2.py',
    'test_agent_memory_component3.py',
    'test_reactive_learning_component4.py',
    'test_governed_tool_execution_component5.py',
    'test_agent_workspace_component6.py',
]
REPORT_DIR = ROOT / 'reports' / 'test_runners'


def live_database_check() -> tuple[bool, str]:
    """Probe DB using project client: read-only, never creates a graph."""
    if importlib.util.find_spec('falkordb') is None:
        return False, 'FalkorDB Python package missing; install pip requirements.txt'
    try:
        sys.path.insert(0, str(ROOT))
        from backend.app.config import Settings
        from backend.app.graph.client import FalkorGraphClient
        client = FalkorGraphClient(Settings.from_env())
        client.health_check()
    except Exception as exc:
        return False, f'Database health check failed: {type(exc).__name__}: {str(exc)[:180]}'
    return True, 'FalkorDB Python client and server responded to health check'


def junit_stats(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == 'testsuite' else root.findall('.//testsuite')
    # pytest emits one testsuite in testsuites; avoid double counting parent suites.
    suites = [s for s in suites if not s.findall('testsuite')]
    return {name: sum(int(s.get(name, 0)) for s in suites) for name in ('tests', 'failures', 'errors', 'skipped')}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--suite', choices=('components', 'database', 'all'), default='all')
    parser.add_argument('--check', action='store_true', help='Print requirements/coverage without running tests')
    parser.add_argument('--report-dir', type=Path, default=REPORT_DIR)
    parser.add_argument('--pytest-arg', action='append', default=[], help='Forward an option to pytest (repeatable)')
    args = parser.parse_args(argv)
    if importlib.util.find_spec('pytest') is None:
        print('BLOCKED: pytest missing. Install: python -m pip install -r requirements.txt', file=sys.stderr)
        return 2
    missing = [name for name in COMPONENTS if not (ROOT / 'backend' / 'tests' / name).is_file()]
    if missing:
        print('BLOCKED: Missing component test files:', ', '.join(missing), file=sys.stderr)
        return 2
    db_ok, db_message = live_database_check()
    print(f'Components 1–6: {len(COMPONENTS)} test files found')
    print(('DATABASE READY: ' if db_ok else 'DATABASE BLOCKED: ') + db_message)
    print('Database tests: pytest -m integration (isolated test graph fixtures)')
    if args.check:
        return 0 if args.suite == 'components' or db_ok else 2
    if args.suite in ('database', 'all') and not db_ok:
        print('BLOCKED: Database suite cannot be certified. Component tests may still run.', file=sys.stderr)
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    specs = []
    if args.suite in ('components', 'all'):
        specs.append(('components', [f'backend/tests/{name}' for name in COMPONENTS]))
    if args.suite in ('database', 'all') and db_ok:
        specs.append(('database', ['-m', 'integration', 'backend/tests']))
    records = []
    for label, selectors in specs:
        xml = report_dir / f'{label}_junit.xml'
        command = [sys.executable, '-m', 'pytest', '-q', '-ra', *selectors, f'--junitxml={xml}', *args.pytest_arg]
        print(f'\n=== {label.upper()} ===\n{sys.executable} -m pytest -q -ra ' + ' '.join(selectors))
        # Original output is streamed; no secret environment variables are echoed.
        code = subprocess.call(command, cwd=ROOT)
        stat = junit_stats(xml)
        if stat['tests'] == 0 or (label == 'database' and stat['skipped']):
            if not code:
                code = 2
            print(f'BLOCKED: {label} had no executed tests or skipped database tests.')
        records.append({'suite': label, 'exit_code': code, **stat, 'junit': str(xml)})
    if args.suite in ('database', 'all') and not db_ok:
        records.append({'suite': 'database', 'exit_code': 2, 'blocked_reason': db_message,
                        'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0})
    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'requested_suite': args.suite, 'database_preflight': db_message,
              'suites': records, 'passed': all(r['exit_code'] == 0 for r in records)}
    (report_dir / 'integration_summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'\nSummary: {report_dir / "integration_summary.json"}')
    return 0 if report['passed'] else 2 if not db_ok and args.suite in ('database', 'all') else 1


if __name__ == '__main__':
    raise SystemExit(main())
