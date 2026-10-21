"""Run GraphHacks Playwright browser tests from Python (Windows and Linux).

Commands (from repository root):
  python scripts/run_browser_tests.py --check
  python scripts/run_browser_tests.py --suite ui         # mocked UI only; safe
  python scripts/run_browser_tests.py --suite live       # existing Vite + API
  python scripts/run_browser_tests.py --suite legacy     # isolated Phase 12/13

The UI suite uses a real Chromium browser with explicitly mocked read endpoints:
it does NOT establish live agent, connector or FalkorDB correctness. The live
suite performs only authenticated reads. Legacy scripts create disposable
FalkorDB graphs; they do not write to company_brain.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'
REPORT_DIR = ROOT / 'reports' / 'test_runners'


def tool(name: str) -> str | None:
    candidates = (name + '.cmd', name) if os.name == 'nt' else (name,)
    return next((p for candidate in candidates if (p := shutil.which(candidate))), None)


def reachable(base_url: str) -> bool:
    try:
        with urlopen(base_url.rstrip('/') + '/', timeout=2) as reply:
            return reply.status < 500
    except (URLError, OSError, TimeoutError):
        return False


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, timeout=12, check=False)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--suite', choices=('ui', 'live', 'legacy'), default='ui')
    parser.add_argument('--check', action='store_true', help='Check dependencies and test files')
    parser.add_argument('--base-url', default='http://127.0.0.1:5174', help='Existing Vite URL; ui suite launches Vite if absent')
    parser.add_argument('--report-dir', type=Path, default=REPORT_DIR)
    parser.add_argument('--headed', action='store_true', help='Show Chromium while running')
    args = parser.parse_args(argv)
    npm, npx = tool('npm'), tool('npx')
    deps = (FRONTEND / 'node_modules' / '@playwright' / 'test')
    spec = FRONTEND / 'e2e' / 'agent-workspace.spec.ts'
    print('Playwright spec:', spec.relative_to(ROOT), 'FOUND' if spec.is_file() else 'MISSING')
    print('npm:', npm or 'NOT FOUND', '| npx:', npx or 'NOT FOUND')
    print('Frontend dependencies:', 'INSTALLED' if deps.exists() else 'MISSING (cd frontend && npm ci)')
    if not spec.is_file() or not npm or not npx or not deps.exists():
        print('BLOCKED: Install dependencies before browser tests. Then: cd frontend && npx playwright install chromium')
        return 2
    if args.check:
        print('Prerequisite check passed; Chromium must also be installed for execution.')
        return 0
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    records = []
    proc = None
    env = os.environ.copy()
    try:
        if args.suite == 'legacy':
            # Existing scripts own isolated, randomly named test graphs.
            for filename in ('verify_phase12_ui.py', 'verify_phase13_ui.py'):
                print(f'\nRunning isolated legacy acceptance: {filename}')
                status = subprocess.call([sys.executable, str(ROOT / 'scripts' / filename)], cwd=ROOT)
                records.append({'test': filename, 'exit_code': status})
        else:
            base = args.base_url.rstrip('/')
            if args.suite == 'ui' and not reachable(base):
                # UI contract only: no backend is started or touched.
                if base != 'http://127.0.0.1:5174':
                    print('BLOCKED: For custom --base-url, start Vite manually first.')
                    return 2
                env.update({'VITE_DEV_PORT': '5174', 'VITE_API_BASE_URL': '',
                            'VITE_TEST_TOKEN': 'test-asteria-admin-token', 'VITE_TENANT_ID': 'asteria'})
                print('Launching local Vite for mocked browser UI tests...')
                with (report_dir / 'vite_browser.log').open('w', encoding='utf-8') as logfile:
                    proc = subprocess.Popen([npm, 'run', 'dev'], cwd=FRONTEND, env=env,
                                            stdout=logfile, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline and not reachable(base) and proc.poll() is None:
                    time.sleep(.5)
                if not reachable(base):
                    print('BLOCKED: Vite did not start. Inspect reports/test_runners/vite_browser.log')
                    return 2
            if not reachable(base):
                print('BLOCKED: Vite unavailable. Start backend and frontend for live checks.')
                return 2
            env['PHASE13_BASE_URL'] = base
            if args.suite == 'live':
                env['GRAPH_HACKS_BROWSER_LIVE'] = '1'
                env.setdefault('VITE_TEST_TOKEN', 'test-asteria-admin-token')
                env.setdefault('VITE_TENANT_ID', 'asteria')
            else:
                env.pop('GRAPH_HACKS_BROWSER_LIVE', None)
            cmd = [npx, '--no-install', 'playwright', 'test', 'e2e/agent-workspace.spec.ts',
                   '--grep', 'LIVE_BACKEND:' if args.suite == 'live' else 'UI_CONTRACT:',
                   '--reporter=line']
            if args.headed:
                cmd.append('--headed')
            print(f'Running {args.suite} Playwright suite against {base}')
            with (report_dir / f'browser_{args.suite}.log').open('w', encoding='utf-8') as logfile:
                done = subprocess.run(cmd, cwd=FRONTEND, env=env, stdout=logfile,
                                      stderr=subprocess.STDOUT, text=True, timeout=250)
            print(f'Playwright exit code: {done.returncode}; log: {report_dir / f"browser_{args.suite}.log"}')
            if done.returncode:
                tail = (report_dir / f'browser_{args.suite}.log').read_text(encoding='utf-8', errors='replace')[-2400:]
                print(tail)
            records.append({'test': f'agent-workspace ({args.suite})', 'exit_code': done.returncode})
    except (OSError, subprocess.TimeoutExpired) as exc:
        print('BLOCKED:', type(exc).__name__, str(exc)[:200])
        return 2
    finally:
        stop(proc)
        if records:
            report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'suite': args.suite,
                      'mode': 'MOCKED_BROWSER_UI' if args.suite == 'ui' else 'LIVE_READ_ONLY' if args.suite == 'live' else 'ISOLATED_LEGACY',
                      'results': records, 'passed': all(r['exit_code'] == 0 for r in records)}
            (report_dir / f'browser_{args.suite}_summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if records and all(r['exit_code'] == 0 for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
