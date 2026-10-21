"""Measure the opt-in incident fast path on the user's running Asteria graph.

Requires an existing .env with GROQ_API_KEY. Performs one allowed read-only
incident_context operation, a single Groq synthesis request, and persists agent
trace only (no business data modifications). Never prints keys/source secrets.
"""
from __future__ import annotations
import json
import sys
from dotenv import load_dotenv
load_dotenv('.env')
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.agent_runtime.harness import AgentHarness, AgentSettings
from backend.app.agent_runtime.provider import OpenAICompatibleProvider
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.agent_runtime.store import GraphRunStore

GRAPH='asteria_company_brain_v1'
TENANT='asteria'
INCIDENT='INC-AST-ROUTE-OUTAGE'


class UsageMeter:
    def __init__(self, provider):
        self.provider=provider
        self.name=provider.name
        self.model=provider.model
        self.calls=[]
    def complete(self,messages,tools,*,remaining_seconds,max_output_tokens):
        result=self.provider.complete(messages,tools,remaining_seconds=remaining_seconds,
                                      max_output_tokens=max_output_tokens)
        self.calls.append({'messages':len(messages), 'request_chars':len(json.dumps(messages,default=str)),
                           'tools_offered':len(tools), 'max_completion_tokens':max_output_tokens,
                           'total_tokens':result.tokens,
                           'prompt_tokens':result.prompt_tokens,
                           'completion_tokens':result.completion_tokens,
                           'reasoning_tokens':result.reasoning_tokens,
                           'finish_reason':result.finish_reason})
        return result


def main():
    settings=Settings.from_env().model_copy(update={'falkordb_graph':GRAPH,'tenant_id':TENANT})
    client=FalkorGraphClient(settings)
    snapshot=GraphSnapshot.load(client)
    if not snapshot.node(INCIDENT):
        print(json.dumps({'error':'Requested Asteria incident not found','passed':False}));return 2
    provider=UsageMeter(OpenAICompatibleProvider())
    store=GraphRunStore(client)
    harness=AgentHarness(provider=provider,tools=ToolRegistry(lambda:GraphSnapshot.load(client)),
                         store=store,tenant=TENANT)
    print(f'Executing deterministic incident skill: graph={GRAPH}, tenant={TENANT}, model={provider.model}',flush=True)
    report=harness.run(AgentSettings(goal=(f'Investigate {INCIDENT}, explain recorded schema errors, '
                         'chronology, competing hypotheses and uncertainty. Read-only; cite actual evidence.'),
                source_entity_id=INCIDENT,execution_mode='incident_skill',
                max_steps=2,max_tokens=7000,max_seconds=175,allow_external_model=True),
                       subject='phase1_incident_skill_audit')
    try:
        persisted = store.get(report.id) is not None
    except Exception:
        persisted=False
    passed = (report.status in {'COMPLETED','INSUFFICIENT_EVIDENCE'} and bool(report.answer)
              and bool(report.citations) and len(provider.calls)==1 and persisted)
    print(json.dumps({'smoke_pass':passed,'run_id':report.id,'status':report.status,
          'error':report.error,'model_calls':len(provider.calls),
          'model_usage':provider.calls,'total_tokens':report.tokens_used,
          'reference_previous_run_tokens':4537,
          'delta_vs_previous_tokens':report.tokens_used-4537,
          'trace_kinds':[step['kind'] for step in report.trace],
          'citations':report.citations,'knowledge_gaps':report.knowledge_gaps,
          'answer':report.answer,'persisted':persisted},indent=2,ensure_ascii=False))
    return 0 if passed else 1

if __name__=='__main__':
    sys.exit(main())
