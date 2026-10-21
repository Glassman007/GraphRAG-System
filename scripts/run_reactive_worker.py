"""Replay tenant-scoped durable GraphHacks Component 4 events after process restarts.

Run in a separate supervisor-managed process, e.g.:
  python scripts/run_reactive_worker.py --tenant asteria --poll-seconds 10
  python scripts/run_reactive_worker.py --tenant asteria --once

Does not invoke external models or execute business actions.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.agent_runtime.memory import AgentMemory
from backend.app.agent_runtime.memory_store import GraphMemoryStore
from backend.app.agent_runtime.reactive import ReactiveLearning
from backend.app.agent_runtime.reactive_store import GraphReactiveStore
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot


def serve(tenant: str, *, once: bool = False, poll_seconds: int = 10) -> None:
    settings = Settings.from_env().model_copy(update={'tenant_id': tenant})
    client = FalkorGraphClient(settings)
    runtime = ReactiveLearning(store=GraphReactiveStore(client),
                               memory=AgentMemory(backend=GraphMemoryStore(client),
                                   snapshot_factory=lambda: GraphSnapshot.load(client),tenant=tenant),
                               snapshot_factory=lambda: GraphSnapshot.load(client),tenant=tenant)
    while True:
        try:
            processed = runtime.process(limit=25)
            if processed:
                logging.info('Processed %s durable changes for tenant %s', len(processed), tenant)
        except Exception:
            logging.exception('Change processor failed; retained events can retry after lease expiry')
            if once:
                raise
        if once:
            return
        time.sleep(max(2, poll_seconds))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant', required=True, help='Exact configured tenant ID')
    parser.add_argument('--once', action='store_true', help='Process pending events once and exit')
    parser.add_argument('--poll-seconds', type=int, default=10)
    args = parser.parse_args()
    if not args.tenant or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in args.tenant):
        parser.error('Invalid tenant ID')
    logging.basicConfig(level=logging.INFO)
    try:
        serve(args.tenant, once=args.once, poll_seconds=args.poll_seconds)
    except KeyboardInterrupt:
        pass
