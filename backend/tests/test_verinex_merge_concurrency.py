"""Cross-component regression: concurrent Supervisor calls share the Groq pacer."""
from __future__ import annotations

import threading

from backend.app.agent_runtime.provider import TokenPacer


def test_waiting_specialist_does_not_lock_out_completed_model_call(monkeypatch):
    import backend.app.agent_runtime.provider as provider

    limiter = TokenPacer(2000)
    first = limiter.reserve(1700, 70)
    sleeper_entered = threading.Event()
    resume_waiter = threading.Event()
    settled = threading.Event()
    errors: list[Exception] = []
    reservations = []

    def held_sleep(duration):
        sleeper_entered.set()
        assert resume_waiter.wait(3), 'Test-controlled clock stalled'

    monkeypatch.setattr(provider.time, 'sleep', held_sleep)

    def waiting_specialist():
        try:
            reservations.append(limiter.reserve(1000, 70))
        except Exception as exc:
            errors.append(exc)

    def completed_specialist():
        try:
            limiter.settle(first, 100)
            settled.set()
        except Exception as exc:
            errors.append(exc)

    waiter = threading.Thread(target=waiting_specialist, daemon=True)
    worker = threading.Thread(target=completed_specialist, daemon=True)
    waiter.start()
    try:
        assert sleeper_entered.wait(1), 'Quota pacing did not enter a wait'
        worker.start()
        assert settled.wait(0.5), 'Waiting specialist held a lock needed to settle tokens'
    finally:
        resume_waiter.set()
        waiter.join(timeout=2)
        if worker.ident is not None:
            worker.join(timeout=2)
    assert not errors
    assert len(reservations) == 1
