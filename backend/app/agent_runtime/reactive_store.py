"""Durable FalkorDB event inbox, change audit and conditional processing leases.

Uses the private Component 3 graph and tenant-scoped keys. No process-global queue.
Operations are conditional graph updates; the event ID + lease token guard replay.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.services.phase3_utils import node_dict


class GraphReactiveStore:
    def __init__(self, client):
        self.tenant = client.settings.tenant_id
        self.graph = client.db.select_graph(client.settings.falkordb_graph + '_agent_memory')

    def _write(self, cypher, params):
        return self.graph.query(cypher, params).result_set

    def _read(self, cypher, params):
        return self.graph.ro_query(cypher, params).result_set

    @staticmethod
    def _doc(node):
        obj = node_dict(node) or {}
        result = json.loads(obj.get('document_json') or '{}')
        if obj.get('status'):
            result['status'] = obj['status']
        return result

    def enqueue(self, event: dict) -> dict:
        if event['tenant_id'] != self.tenant:
            raise PermissionError('Wrong tenant')
        rows = self._write('''
            MERGE (e:ReactiveChange {tenant_id:$tenant,id:$id})
            ON CREATE SET e.status='PENDING',e.attempts=0,e.lease_until=0,
                e.created_at=$created,e.document_json=$doc
            RETURN e
        ''', {'tenant': self.tenant, 'id': event['id'], 'created': event['occurred_at'],
              'doc': json.dumps(event, ensure_ascii=False)})
        return self._doc(rows[0][0])

    def claim(self) -> dict | None:
        now = time.time()
        lease_token = uuid.uuid4().hex
        rows = self._write('''
            MATCH (e:ReactiveChange {tenant_id:$tenant})
            WHERE e.status='PENDING' OR
                  (e.status='RETRY' AND coalesce(e.next_attempt_at,0) <= $now) OR
                  (e.status='PROCESSING' AND coalesce(e.lease_until,0) < $now)
            WITH e ORDER BY e.created_at ASC LIMIT 1
            SET e.status='PROCESSING',e.lease_until=$until,e.lease_token=$token
            RETURN e
        ''', {'tenant': self.tenant, 'now': now, 'until': now + 90, 'token': lease_token})
        if not rows:
            return None
        doc = self._doc(rows[0][0])
        doc['lease_token'] = lease_token
        return doc

    def finish(self, event_id: str, *, token: str, result: dict):
        # Never let an expired worker overwrite a newer lease's result.
        current = self._read('''
            MATCH (e:ReactiveChange {tenant_id:$tenant,id:$id,status:'PROCESSING',lease_token:$token})
            RETURN e LIMIT 1
        ''', {'tenant': self.tenant, 'id': event_id, 'token': token})
        if not current:
            raise RuntimeError('Event lease lost before acknowledgement')
        merged = {**self._doc(current[0][0]), **result}
        rows = self._write('''
            MATCH (e:ReactiveChange {tenant_id:$tenant,id:$id,status:'PROCESSING',lease_token:$token})
            SET e.status=$status,e.document_json=$doc,e.lease_token='',e.lease_until=0,
                e.finished_at=$finished RETURN e.id
        ''', {'tenant': self.tenant, 'id': event_id, 'token': token,
              'status': result['status'], 'doc': json.dumps(merged, ensure_ascii=False),
              'finished': datetime.now(timezone.utc).isoformat()})
        if not rows:
            raise RuntimeError('Event lease lost before acknowledgement')

    def fail(self, event_id: str, *, token: str, error: str):
        rows = self._read('''
            MATCH (e:ReactiveChange {tenant_id:$tenant,id:$id,status:'PROCESSING',lease_token:$token})
            RETURN e LIMIT 1
        ''', {'tenant': self.tenant, 'id': event_id, 'token': token})
        if not rows:
            return
        event = self._doc(rows[0][0])
        attempts = int(event.get('attempts') or 0) + 1
        state = 'RETRY' if attempts < int(event.get('max_attempts') or 3) else 'FAILED_NEEDS_REVIEW'
        event.update(status=state, attempts=attempts, error=error)
        self._write('''
            MATCH (e:ReactiveChange {tenant_id:$tenant,id:$id,status:'PROCESSING',lease_token:$token})
            SET e.status=$status,e.attempts=$attempts,e.next_attempt_at=$next,
                e.lease_token='',e.lease_until=0,e.document_json=$doc
        ''', {'tenant': self.tenant, 'id': event_id, 'token': token, 'status': state,
              'attempts': attempts, 'next': time.time() + min(300, 2 ** attempts),
              'doc': json.dumps(event, ensure_ascii=False)})

    def list_events(self, limit: int = 30):
        rows = self._read('''
            MATCH (e:ReactiveChange {tenant_id:$tenant})
            RETURN e ORDER BY e.created_at DESC LIMIT $limit
        ''', {'tenant': self.tenant, 'limit': min(100, max(1, limit))})
        return [self._doc(row[0]) for row in rows]

    def get(self, event_id: str):
        rows = self._read('''MATCH (e:ReactiveChange {tenant_id:$tenant,id:$id}) RETURN e LIMIT 1''',
                          {'tenant': self.tenant, 'id': event_id})
        return self._doc(rows[0][0]) if rows else None

    def affected_memories(self, ids: list[str]) -> list[dict]:
        # Safe upper bound instead of silently truncating a 10k+ tenant scan.
        rows = self._read('''
            MATCH (m:AgentKnowledge {tenant_id:$tenant,status:'VERIFIED',scope:'SHARED'})
            RETURN m LIMIT 10001
        ''', {'tenant': self.tenant})
        if len(rows) > 10000:
            raise RuntimeError('Memory impact scan exceeds 10000 records; index/backfill review required')
        targets = set(ids)
        return [v for row in rows if (v := self._doc(row[0])) and
                ({v.get('subject_id'), v.get('value')} | set(v.get('citations') or [])) & targets]

    def affected_checkpoints(self, ids: list[str]) -> list[dict]:
        rows = self._read('''
            MATCH (c:AgentWorkflowCheckpoint {tenant_id:$tenant}) RETURN c LIMIT 10001
        ''', {'tenant': self.tenant})
        if len(rows) > 10000:
            raise RuntimeError('Checkpoint impact scan exceeds 10000 records; review required')
        targets = set(ids)
        return [cp for row in rows if (cp := self._doc(row[0])) and (
            cp.get('source') in targets or any(
                targets & set((t.get('result') or {}).get('citations') or []) for t in cp.get('tasks') or []))]

    def revise_memory(self, old: dict, new: dict, *, event_id: str):
        if old.get('tenant_id') != self.tenant or new.get('tenant_id') != self.tenant:
            raise PermissionError('Wrong tenant memory')
        # Historical version lives in this isolated graph. Replays MERGE same archival key.
        self._write('''
            MERGE (h:AgentMemoryRevision {tenant_id:$tenant,memory_id:$id,event_id:$event})
            ON CREATE SET h.revision=$revision,h.document_json=$doc,h.created_at=$created
        ''', {'tenant': self.tenant, 'id': old['id'], 'event': event_id,
              'revision': int(old.get('revision') or 1), 'doc': json.dumps(old, ensure_ascii=False),
              'created': datetime.now(timezone.utc).isoformat()})
        rows = self._write('''
            MATCH (m:AgentKnowledge {tenant_id:$tenant,id:$id})
            WHERE coalesce(m.revision,1)=$previous
            SET m.revision=$revision,m.document_json=$doc,m.status=$status,m.scope=$scope
            RETURN m.id
        ''', {'tenant': self.tenant, 'id': old['id'], 'previous': int(old.get('revision') or 1),
              'revision': new['revision'], 'doc': json.dumps(new, ensure_ascii=False),
              'status': new['status'], 'scope': new['scope']})
        if not rows:
            # Revisions are serial; a concurrent promotion/review must be reconciled, not overwritten.
            raise RuntimeError('Concurrent memory revision conflict')

    def revise_checkpoint(self, old: dict, new: dict, *, event_id: str):
        if old.get('tenant') != self.tenant or new.get('tenant') != self.tenant:
            raise PermissionError('Wrong tenant checkpoint')
        self._write('''
            MERGE (h:AgentCheckpointRevision {tenant_id:$tenant,run_id:$id,event_id:$event})
            ON CREATE SET h.revision=$revision,h.document_json=$doc,h.created_at=$created
        ''', {'tenant': self.tenant, 'id': old['id'], 'event': event_id,
              'revision': int(old.get('revision') or 1), 'doc': json.dumps(old, ensure_ascii=False),
              'created': datetime.now(timezone.utc).isoformat()})
        rows = self._write('''
            MATCH (c:AgentWorkflowCheckpoint {tenant_id:$tenant,id:$id,owner:$owner})
            WHERE c.revision=$previous
            SET c.revision=$revision,c.document_json=$doc,c.updated_at=$updated
            RETURN c.id
        ''', {'tenant': self.tenant, 'id': old['id'], 'owner': old['owner'],
              'previous': int(old.get('revision') or 1), 'revision': new['revision'],
              'doc': json.dumps(new, ensure_ascii=False), 'updated': new['updated_at']})
        if not rows:
            raise RuntimeError('Concurrent checkpoint revision conflict')

    def save_outcome(self, outcome: dict) -> dict:
        if outcome['tenant_id'] != self.tenant:
            raise PermissionError('Wrong tenant action outcome')
        rows = self._write('''
            MERGE (o:VerifiedActionOutcome {tenant_id:$tenant,id:$id})
            ON CREATE SET o.action_id=$action,o.target_id=$target,o.result=$result,o.verified_at=$verified,
                o.document_json=$doc
            RETURN o
        ''', {'tenant': self.tenant, 'id': outcome['id'], 'action': outcome['action_id'],
              'result': outcome['result'], 'verified': outcome['verified_at'],
              'target':outcome.get('target_id') or '',
              'doc': json.dumps(outcome, ensure_ascii=False)})
        return self._doc(rows[0][0])

    def outcomes_for_entities(self, ids: list[str], limit: int = 15) -> list[dict]:
        rows = self._read('''
            MATCH (o:VerifiedActionOutcome {tenant_id:$tenant})
            WHERE o.action_id IN $ids OR o.target_id IN $ids RETURN o ORDER BY o.verified_at DESC LIMIT $limit
        ''', {'tenant': self.tenant, 'ids': ids, 'limit': min(limit, 25)})
        return [self._doc(row[0]) for row in rows]
