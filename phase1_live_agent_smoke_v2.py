"""Phase 1 live investigator retry: bounded, observable, and read-only for business data.

This is a TEST SCRIPT ONLY. It does not patch VERINEX modules.
It calls Groq using the already-configured model, exposes only three relevant
read-only tools, and writes AgentRun/AgentStep telemetry to the Asteria graph.
It deliberately reports incomplete runs as failures rather than masking them.
"""
from __future__ import annotations

import json
import sys
from dotenv import load_dotenv

load_dotenv('.env')

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.agent_runtime.provider import OpenAICompatibleProvider
from backend.app.agent_runtime.harness import AgentHarness, AgentSettings
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.agent_runtime.store import GraphRunStore

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
ALLOWED_TOOLS = frozenset({'incident_context', 'graph_neighbors', 'get_entity'})


class NarrowToolRegistry(ToolRegistry):
    def execute(self, name, arguments):
        if name not in ALLOWED_TOOLS:
            raise ValueError('Tool unavailable in narrow Phase 1 smoke test')
        return super().execute(name, arguments)


class MeteredProvider:
    """Narrow tool *advertising* and audit call cost without modifying the provider."""
    def __init__(self, real):
        self.real = real
        self.name = real.name
        self.model = real.model
        self.calls = []

    def complete(self, messages, tools, *, remaining_seconds, max_output_tokens):
        offered = [t for t in tools if t.get('function', {}).get('name') in ALLOWED_TOOLS]
        phase = 'tool_choice' if offered else ('plan_or_final')
        metadata = {
            'phase': phase,
            'message_count': len(messages),
            'request_chars': len(json.dumps(messages, default=str)) + len(json.dumps(offered, default=str)),
            'offered_tools': [t['function']['name'] for t in offered],
            'max_output_tokens': max_output_tokens,
        }
        try:
            result = self.real.complete(messages, offered,
                                        remaining_seconds=remaining_seconds,
                                        max_output_tokens=max_output_tokens)
            metadata.update({
                'actual_total_tokens': result.tokens,
                'tool_calls': [t['name'] for t in result.calls],
                'finish_reason': result.finish_reason,
            })
            return result
        except Exception as exc:
            metadata['provider_exception'] = type(exc).__name__
            raise
        finally:
            self.calls.append(metadata)
            print('MODEL_CALL ' + json.dumps(metadata, ensure_ascii=False), flush=True)


def main() -> int:
    cfg = Settings.from_env().model_copy(update={
        'falkordb_graph': GRAPH,
        'tenant_id': TENANT,
    })
    client = FalkorGraphClient(cfg)
    snapshot = GraphSnapshot.load(client)
    if INCIDENT not in snapshot.nodes:
        print(json.dumps({'status': 'PREFLIGHT_FAILED', 'reason': 'Asteria incident missing'}))
        return 2

    provider = MeteredProvider(OpenAICompatibleProvider())
    store = GraphRunStore(client)
    harness = AgentHarness(
        provider=provider,
        tools=NarrowToolRegistry(lambda: GraphSnapshot.load(client)),
        store=store,
        tenant=TENANT,
    )
    print(f'Phase 1 narrow retry: graph={GRAPH}, tenant={TENANT}, model={provider.model}', flush=True)
    run = harness.run(
        AgentSettings(
            goal=(
                f'Investigate Asteria incident {INCIDENT}. First use incident_context '
                'to inspect the incident. Then give a short evidence-grounded conclusion, '
                'citing observed IDs. Separate graph assertions from proven causes. '
                'Do not execute business actions.'
            ),
            source_entity_id=INCIDENT,
            max_steps=2,       # one model tool turn, then mandatory finalization
            max_tokens=7000,   # do not raise the budget to hide inefficiency
            max_seconds=175,
            allow_external_model=True,
        ),
        subject='phase1_narrow_audit',
    )
    try:
        stored = store.get(run.id)
        persistence_error = None
    except Exception as exc:
        stored = None
        persistence_error = type(exc).__name__

    tool_events = [
        {'tool': t.get('tool'), 'status': t.get('status')}
        for t in run.trace if t.get('kind') in ('TOOL', 'TOOL_ERROR', 'DUPLICATE_TOOL')
    ]
    success = (run.status in ('COMPLETED', 'INSUFFICIENT_EVIDENCE')
               and bool(run.answer) and bool(run.citations)
               and any(t['status'] == 'RECORDED' for t in tool_events)
               and stored is not None)
    print(json.dumps({
        'smoke_pass': success,
        'run_id': run.id,
        'status': run.status,
        'error': run.error,
        'tokens_used': run.tokens_used,
        'provider_calls': provider.calls,
        'tools': tool_events,
        'trace_kinds': [t.get('kind') for t in run.trace],
        'citations': run.citations,
        'knowledge_gaps': run.knowledge_gaps,
        'answer': run.answer[:2500],
        'persisted': stored is not None,
        'persisted_trace_steps': len((stored or {}).get('trace', [])),
        'persistence_error': persistence_error,
    }, indent=2, ensure_ascii=False))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
