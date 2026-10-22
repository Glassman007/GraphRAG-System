"""Tenant-scoped FalkorDB persistence for supervisor DAGs, task states and handoffs.

Graph writes are limited to internal execution telemetry. All business graph tools
remain read-only. Callers must not treat telemetry as an approved business action.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase3_utils import node_dict


class GraphSupervisorStore:
    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self._lock = threading.RLock()

    def start(self, run: dict[str, Any]) -> None:
        with self._lock:
            self.client.query('''
                CREATE (r:Entity:SupervisorRun {tenant_id:$tenant,id:$id,goal:$goal,
                  subject:$subject,status:'RUNNING',provider:$provider,model:$model,
                  source_entity_id:$source_id,source_resolution_method:$resolution,
                  plan_rationale:$rationale,started_at:$started_at})
            ''', {'tenant': self.client.settings.tenant_id, 'id': run['id'],
                  'goal': run['goal'], 'subject': run['subject'], 'provider': run['provider'],
                  'model': run['model'], 'source_id': run.get('source_entity_id') or '',
                  'resolution': run.get('source_resolution_method') or '',
                  'rationale': run.get('plan_rationale') or '',
                  'started_at': run['started_at']})

    def task(self, run_id: str, task: dict) -> None:
        # Ownership & progress are serialized per run, with no detached task writes.
        with self._lock:
            self.client.query('''
                MATCH (r:Entity:SupervisorRun {tenant_id:$tenant,id:$run})
                MERGE (t:Entity:SupervisorTask {tenant_id:$tenant,id:$id})
                SET t.task_id=$task_id,t.objective=$objective,t.capability=$capability,
                    t.depends_on=$deps,t.status=$status,t.agent_id=$agent,
                    t.attempts=$attempts,t.result_json=$result,t.error=$error,
                    t.started_at=$started_at,t.finished_at=$finished_at
                MERGE (r)-[:HAS_SUPERVISOR_TASK]->(t)
            ''', {'tenant': self.client.settings.tenant_id, 'run': run_id,
                  'id': f'{run_id}:TASK:{task["id"]}', 'task_id': task['id'],
                  'objective': task['objective'], 'capability': task['capability'],
                  'deps': json.dumps(task['depends_on']), 'status': task['status'],
                  'agent': task.get('agent_id') or '', 'attempts': task['attempts'],
                  'result': json.dumps(task.get('result')), 'error': (task.get('error') or '')[:200],
                  'started_at': task.get('started_at') or '', 'finished_at': task.get('finished_at') or ''})

    def event(self, run_id: str, event: dict) -> None:
        with self._lock:
            self.client.query('''
                MATCH (r:Entity:SupervisorRun {tenant_id:$tenant,id:$run})
                CREATE (e:Entity:SupervisorEvent {tenant_id:$tenant,id:$id,
                  event_index:$idx,kind:$kind,summary:$summary,
                  task_id:$task_id,agent_id:$agent_id,status:$status,created_at:$created_at})
                CREATE (r)-[:HAS_SUPERVISOR_EVENT]->(e)
            ''', {'tenant': self.client.settings.tenant_id, 'run': run_id,
                  'id': f'{run_id}:EVENT:{event["index"]:04d}', 'idx': event['index'],
                  'kind': event['kind'], 'summary': event['summary'],
                  'task_id': event['task_id'], 'agent_id': event['agent_id'],
                  'status': event['status'], 'created_at': event['created_at']})

    def finish(self, run_id: str, result: dict) -> None:
        with self._lock:
            self.client.query('''
                MATCH (r:Entity:SupervisorRun {tenant_id:$tenant,id:$run})
                SET r.status=$status,r.answer=$answer,r.citations=$citations,
                    r.knowledge_gaps=$gaps,r.escalations=$escalations,r.conflicts=$conflicts,
                    r.tokens_used=$tokens,r.error=$error,r.finished_at=$finished_at
            ''', {'tenant': self.client.settings.tenant_id, 'run': run_id,
                  'status': result['status'], 'answer': result['answer'],
                  'citations': json.dumps(result['citations']),
                  'gaps': json.dumps(result['knowledge_gaps']),
                  'escalations': json.dumps(result['escalations']),
                  'conflicts': json.dumps(result['conflicts']),
                  'tokens': result['tokens_used'], 'error': (result.get('error') or '')[:250],
                  'finished_at': result['finished_at']})

    def get(self, run_id: str) -> dict | None:
        params = {'tenant': self.client.settings.tenant_id, 'id': run_id}
        rows = self.client.read('''
            MATCH (r:Entity:SupervisorRun {tenant_id:$tenant,id:$id}) RETURN r
        ''', params).result_set
        if not rows:
            return None
        result = node_dict(rows[0][0]) or {}
        for key in ('citations', 'knowledge_gaps', 'escalations', 'conflicts'):
            try:
                result[key] = json.loads(result.get(key) or '[]')
            except (TypeError, ValueError):
                result[key] = []
        rows = self.client.read('''
            MATCH (:Entity:SupervisorRun {tenant_id:$tenant,id:$id})-[:HAS_SUPERVISOR_TASK]->
                  (t:Entity:SupervisorTask {tenant_id:$tenant})
            RETURN t ORDER BY t.task_id ASC
        ''', params).result_set
        tasks = []
        for row in rows:
            task = node_dict(row[0]) or {}
            for key, field, default in (('depends_on', 'depends_on', '[]'), ('result', 'result_json', 'null')):
                try:
                    task[key] = json.loads(task.get(field) or default)
                except (ValueError, TypeError):
                    task[key] = [] if key == 'depends_on' else None
            if task.get('agent_id') == '':
                task['agent_id'] = None
            tasks.append(task)
        result['tasks'] = tasks
        rows = self.client.read('''
            MATCH (:Entity:SupervisorRun {tenant_id:$tenant,id:$id})-[:HAS_SUPERVISOR_EVENT]->
                  (e:Entity:SupervisorEvent {tenant_id:$tenant})
            RETURN e ORDER BY e.event_index ASC
        ''', params).result_set
        result['events'] = [node_dict(row[0]) or {} for row in rows]
        return result
