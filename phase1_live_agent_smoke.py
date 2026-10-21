"""Phase 1: bounded live investigator smoke test against the EXISTING Asteria graph.

No source ingestion, schema mutation, or business actions. The existing
GraphRunStore DOES write AgentRun / AgentStep execution telemetry to Asteria.
The configured Groq provider is called and uses billed/rate-limited tokens.
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


def main() -> int:
    config = Settings.from_env().model_copy(update={
        'falkordb_graph': GRAPH,
        'tenant_id': TENANT,
    })
    client = FalkorGraphClient(config)
    snapshot = GraphSnapshot.load(client)
    if INCIDENT not in snapshot.nodes:
        print(json.dumps({
            'status': 'PREFLIGHT_FAILED',
            'reason': f'Expected incident {INCIDENT} absent from {GRAPH}/{TENANT}',
            'incident_ids': sorted(
                node_id for node_id, data in snapshot.nodes.items()
                if 'Incident' in data.get('_labels', [])
            )[:20],
        }, indent=2))
        return 2

    provider = OpenAICompatibleProvider()
    store = GraphRunStore(client)
    harness = AgentHarness(
        provider=provider,
        tools=ToolRegistry(lambda: GraphSnapshot.load(client)),
        store=store,
        tenant=TENANT,
    )
    print(f'Executing bounded investigation: graph={GRAPH}, tenant={TENANT}, model={provider.model}', flush=True)
    run = harness.run(
        AgentSettings(
            goal=(
                f'Investigate Asteria incident {INCIDENT}. Inspect existing graph records '
                'with read-only tools and determine what the evidence directly supports, '
                'what remains unverified, and which systems are involved. '
                'Do not mutate data, invoke external actions, or assume a root cause.'
            ),
            source_entity_id=INCIDENT,
            max_steps=4,
            max_tokens=7000,
            max_seconds=175,
            allow_external_model=True,
        ),
        subject='phase1_audit',
    )
    try:
        persisted = store.get(run.id)
        persistence_error = None
    except Exception as exc:
        persisted = None
        persistence_error = type(exc).__name__

    tools = [
        {'name': item.get('tool'), 'status': item.get('status')}
        for item in run.trace
        if item.get('kind') in ('TOOL', 'TOOL_ERROR', 'DUPLICATE_TOOL')
    ]
    print(json.dumps({
        'run_id': run.id,
        'status': run.status,
        'error': run.error,
        'model': provider.model,
        'graph': GRAPH,
        'tenant': TENANT,
        'steps_executed': run.steps_executed,
        'tokens_used': run.tokens_used,
        'plan': run.plan,
        'tools': tools,
        'trace_kinds': [item.get('kind') for item in run.trace],
        'citations': run.citations,
        'knowledge_gaps': run.knowledge_gaps,
        'answer': run.answer[:3500],
        'persisted': persisted is not None,
        'persisted_trace_steps': len((persisted or {}).get('trace', [])),
        'persistence_error': persistence_error,
    }, indent=2, ensure_ascii=False))
    return 0 if run.status in ('COMPLETED', 'INSUFFICIENT_EVIDENCE') and tools and persisted is not None else 1


if __name__ == '__main__':
    sys.exit(main())
