"""Tenant-isolated, graph-persisted run/trace records.

Only runtime metadata, bounded summaries and cited entity IDs are persisted. Provider
secrets, hidden reasoning, raw prompts, and unrestricted source documents are not.
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.graph.client import FalkorGraphClient


class GraphRunStore:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def start(self, run: dict[str, Any]) -> None:
        self.client.query('''
            CREATE (r:Entity:AgentRun {tenant_id:$tenant,id:$id,goal:$goal,subject:$subject,
              status:'RUNNING',provider:$provider,model:$model,started_at:$started_at,
              max_steps:$max_steps,source_entity_id:$source_id})
        ''', {'tenant':self.client.settings.tenant_id, 'id':run['id'], 'goal':run['goal'],
              'subject':run['subject'],'provider':run['provider'],'model':run['model'],
              'started_at':run['started_at'],'max_steps':run['max_steps'],
              'source_id':run.get('source_entity_id') or ''})

    def trace(self, run_id: str, step: dict[str, Any]) -> None:
        self.client.query('''
            MATCH (r:Entity:AgentRun {tenant_id:$tenant,id:$run})
            CREATE (s:Entity:AgentStep {tenant_id:$tenant,id:$id,step_index:$index,kind:$kind,
                  tool_name:$tool,status:$status,summary:$summary,entity_ids:$entity_ids,
                  created_at:$created_at})
            CREATE (r)-[:HAS_AGENT_STEP]->(s)
        ''', {'tenant':self.client.settings.tenant_id,'run':run_id,
              'id':f'{run_id}:STEP:{step["index"]:03d}', 'index':step['index'],
              'kind':step['kind'], 'tool':step.get('tool') or '',
              'status':step.get('status') or 'RECORDED','summary':step['summary'][:2000],
              'entity_ids':json.dumps(step.get('entity_ids') or []),
              'created_at':step['created_at']})

    def finish(self, run_id: str, result: dict[str, Any]) -> None:
        self.client.query('''
            MATCH (r:Entity:AgentRun {tenant_id:$tenant,id:$id})
            SET r.status=$status,r.finished_at=$finished_at,r.answer=$answer,
                r.citations=$citations,r.knowledge_gaps=$gaps,r.plan=$plan,
                r.steps_executed=$steps,r.token_usage=$tokens,r.error=$error
        ''', {'tenant':self.client.settings.tenant_id,'id':run_id,'status':result['status'],
              'finished_at':result['finished_at'],'answer':result.get('answer') or '',
              'citations':json.dumps(result.get('citations') or []),
              'gaps':json.dumps(result.get('knowledge_gaps') or []),
              'plan':json.dumps(result.get('plan') or []),
              'steps':result.get('steps_executed') or 0,'tokens':result.get('tokens_used') or 0,
              'error':(result.get('error') or '')[:300]})

    def get(self, run_id: str) -> dict[str, Any] | None:
        params={'tenant':self.client.settings.tenant_id,'id':run_id}
        result=self.client.read('''
            MATCH (r:Entity:AgentRun {tenant_id:$tenant,id:$id}) RETURN r
        ''',params)
        if not result.result_set:
            return None
        from backend.app.services.phase3_utils import node_dict
        value=node_dict(result.result_set[0][0]) or {}
        for key in ('citations','knowledge_gaps','plan'):
            try:value[key]=json.loads(value.get(key) or '[]')
            except (ValueError,TypeError):value[key]=[]
        trace=self.client.read('''
            MATCH (:Entity:AgentRun {tenant_id:$tenant,id:$id})-[:HAS_AGENT_STEP]->(s:Entity:AgentStep {tenant_id:$tenant})
            RETURN s ORDER BY s.step_index ASC
        ''',params)
        steps=[]
        for row in trace.result_set:
            step=node_dict(row[0]) or {}
            try:step['entity_ids']=json.loads(step.get('entity_ids') or '[]')
            except (ValueError,TypeError):step['entity_ids']=[]
            steps.append(step)
        value['trace']=steps
        return value
