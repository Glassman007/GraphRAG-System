"""FalkorDB-backed memory isolated in a dedicated graph, away from graph search/tools.

FalkorDB is the durable source of truth. No Python process-global memory, local JSON
or transcript export is used for persistence. Queries always carry tenant parameters.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from backend.app.services.phase3_utils import node_dict


class GraphMemoryStore:
    def __init__(self, client):
        self.client = client
        self.tenant = client.settings.tenant_id
        self.graph = client.db.select_graph(client.settings.falkordb_graph + '_agent_memory')
        self._lock = threading.RLock()

    def _query(self, statement: str, params: dict):
        return self.graph.query(statement, params)

    def _read(self, statement: str, params: dict):
        return self.graph.ro_query(statement, params)

    @staticmethod
    def _decode(node) -> dict:
        raw = node_dict(node) or {}
        try:
            return json.loads(raw.get('document_json') or '{}')
        except (ValueError, TypeError):
            return {}

    def save(self, entry: dict) -> None:
        if entry['tenant_id'] != self.tenant:
            raise PermissionError('Cross-tenant memory write forbidden')
        with self._lock:
            # Private payloads cannot accidentally appear in a general graph snapshot.
            self._query('''
                MERGE (m:AgentKnowledge {tenant_id:$tenant,id:$id})
                SET m.subject_id=$subject,m.status=$status,m.scope=$scope,
                    m.predicate=$predicate,m.value=$value,m.origin_run_id=$run,
                    m.origin_task_id=$task,m.created_at=$created,m.revision=$revision,
                    m.document_json=$document
            ''', {'tenant': self.tenant, 'id': entry['id'], 'subject': entry['subject_id'],
                  'status': entry['status'], 'scope': entry['scope'], 'predicate': entry['predicate'],
                  'value': entry['value'], 'run': entry['origin_run_id'],
                  'task': entry['origin_task_id'], 'created': entry['created_at'],
                  'revision': int(entry.get('revision') or 1),
                  'document': json.dumps(entry, ensure_ascii=False)})

    def get(self, memory_id: str) -> dict | None:
        result = self._read('''
            MATCH (m:AgentKnowledge {tenant_id:$tenant,id:$id}) RETURN m LIMIT 1
        ''', {'tenant': self.tenant, 'id': memory_id}).result_set
        return self._decode(result[0][0]) if result else None

    def candidates(self, entity_ids: list[str], query: str, limit: int) -> list[dict]:
        # Bounded scan; additional semantic/context/temporal filtering lives in AgentMemory.
        # Include private status for conflict decisions, never return to users unfiltered.
        rows = self._read('''
            MATCH (m:AgentKnowledge {tenant_id:$tenant})
            WHERE m.subject_id IN $entities OR $search <> '' OR size($entities) = 0
            RETURN m ORDER BY m.created_at DESC LIMIT $limit
        ''', {'tenant': self.tenant, 'entities': entity_ids, 'search': query.strip(),
              'limit': min(max(limit, 1), 250)}).result_set
        return [self._decode(row[0]) for row in rows]

    def conflicting(self, subject_id: str, predicate: str, value: str) -> list[dict]:
        rows = self._read('''
            MATCH (m:AgentKnowledge {tenant_id:$tenant,subject_id:$subject,scope:'SHARED',status:'VERIFIED'})
            WHERE toLower(m.predicate) = toLower($predicate)
              AND toLower(m.value) <> toLower($value)
            RETURN m ORDER BY m.created_at DESC LIMIT 100
        ''', {'tenant': self.tenant, 'subject': subject_id, 'predicate': predicate,
              'value': value}).result_set
        return [self._decode(row[0]) for row in rows]

    def private_for_run(self, run_id: str, task_ids: list[str]) -> list[dict]:
        rows = self._read('''
            MATCH (m:AgentKnowledge {tenant_id:$tenant,origin_run_id:$run,scope:'PRIVATE',status:'DRAFT'})
            WHERE m.origin_task_id IN $tasks
            RETURN m ORDER BY m.created_at ASC LIMIT 100
        ''', {'tenant': self.tenant, 'run': run_id, 'tasks': task_ids}).result_set
        return [self._decode(row[0]) for row in rows]

    def checkpoint(self, run_id: str, *, owner: str, payload: dict, revision: int) -> None:
        """Persist after state transitions; last acknowledged checkpoint wins."""
        with self._lock:
            self._query('''
                MERGE (c:AgentWorkflowCheckpoint {tenant_id:$tenant,id:$id})
                ON CREATE SET c.revision = -1
                WITH c WHERE c.revision < $revision AND coalesce(c.owner,'') IN [$owner,'']
                SET c.owner=$owner,c.revision=$revision,c.document_json=$document,
                    c.updated_at=$updated
                RETURN c.id
            ''', {'tenant': self.tenant, 'id': run_id, 'revision': revision,
                  'owner': owner, 'document': json.dumps(payload, ensure_ascii=False),
                  'updated': payload.get('updated_at', '')})

    def load_checkpoint(self, run_id: str, *, owner: str) -> dict | None:
        rows = self._read('''
            MATCH (c:AgentWorkflowCheckpoint {tenant_id:$tenant,id:$id,owner:$owner})
            RETURN c LIMIT 1
        ''', {'tenant': self.tenant, 'id': run_id, 'owner': owner}).result_set
        if not rows:
            return None
        return self._decode(rows[0][0])
