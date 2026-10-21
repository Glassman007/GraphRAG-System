"""Durable tenant-isolated FalkorDB action state with atomic revision/CAS and audit append."""
from __future__ import annotations

import json
from typing import Any

from backend.app.graph.client import FalkorGraphClient


class GraphGovernedActionStore:
    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.tenant = client.settings.tenant_id

    @staticmethod
    def _decode(value: Any) -> dict:
        if hasattr(value, 'properties'):
            value = value.properties
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, dict):
            return json.loads(value.get('document_json') or '{}')
        raise RuntimeError('Invalid persistent governed action')

    def get(self, action_id: str) -> dict | None:
        rows = self.client.read('''MATCH (a:GovernedAction {tenant_id:$tenant,id:$id})
                                     RETURN a.document_json LIMIT 1''',
                                {'tenant':self.tenant,'id':action_id}).result_set
        return self._decode(rows[0][0]) if rows else None

    def create(self, action: dict) -> dict:
        if action['tenant_id'] != self.tenant:
            raise PermissionError('Cross-tenant action denied')
        audit = {'id':'GAUD-CREATE-'+action['id'][5:], 'tenant_id':self.tenant,
                 'action_id':action['id'], 'type':'PROPOSED', 'actor':action['initiator'],
                 'occurred_at':action['created_at'],'revision':1,
                 'details':{'target_id':action['target_id'],'tool_id':action['tool_id'],
                            'evidence_ids':action['evidence_ids'], 'proposal_validation':action['proposal_validation'],
                            'simulation':action['simulation'], 'agent_id':action['agent_id'],
                            'supervisor_run_id':action['supervisor_run_id']}}
        # A single write transaction creates an immutable proposal and matching audit.
        rows = self.client.query('''
          MERGE (a:GovernedAction {tenant_id:$tenant,id:$id})
          ON CREATE SET a.document_json=$doc,a.revision=1,a.status='PROPOSED',a.created_at=$created
          WITH a
          MERGE (e:GovernedActionAudit {tenant_id:$tenant,id:$event_id})
          ON CREATE SET e.action_id=$id,e.document_json=$event_doc,e.occurred_at=$created
          RETURN a.document_json
        ''', {'tenant':self.tenant, 'id':action['id'], 'doc':json.dumps(action,ensure_ascii=False),
              'created':action['created_at'],'event_id':audit['id'],
              'event_doc':json.dumps(audit,ensure_ascii=False)}).result_set
        if not rows:
            raise RuntimeError('Could not persist governed proposal')
        return self._decode(rows[0][0])

    def transition(self, previous: dict, updated: dict, event: dict) -> dict:
        if previous['tenant_id'] != self.tenant or updated['tenant_id'] != self.tenant or event['tenant_id'] != self.tenant:
            raise PermissionError('Cross-tenant transition denied')
        if updated['revision'] != previous['revision']+1 or updated['id'] != previous['id']:
            raise ValueError('Invalid revision transition')
        rows = self.client.query('''
          MATCH (a:GovernedAction {tenant_id:$tenant,id:$id})
          WHERE a.revision=$prior AND a.status=$prior_status
          SET a.document_json=$doc,a.revision=$revision,a.status=$status,a.updated_at=$updated
          WITH a
          CREATE (e:GovernedActionAudit {tenant_id:$tenant,id:$event_id,action_id:$id,
                    occurred_at:$updated,document_json:$event_doc})
          RETURN a.document_json
        ''', {'tenant':self.tenant,'id':updated['id'],'prior':previous['revision'],
              'prior_status':previous['status'],'doc':json.dumps(updated,ensure_ascii=False),
              'revision':updated['revision'],'status':updated['status'],
              'updated':updated['updated_at'],'event_id':event['id'],
              'event_doc':json.dumps(event,ensure_ascii=False)}).result_set
        if not rows:
            raise RuntimeError('Concurrent action state transition: no external action was dispatched by this call')
        return self._decode(rows[0][0])

    def events(self, action_id: str) -> list[dict]:
        if self.get(action_id) is None:
            return []
        rows = self.client.read('''MATCH (e:GovernedActionAudit {tenant_id:$tenant,action_id:$id})
                                   RETURN e.document_json ORDER BY e.occurred_at,e.id''',
                                {'tenant':self.tenant,'id':action_id}).result_set
        return [self._decode(row[0]) for row in rows]

    def list_actions(self, limit: int = 30) -> list[dict]:
        rows = self.client.read('''MATCH (a:GovernedAction {tenant_id:$tenant})
                                   RETURN a.document_json ORDER BY a.created_at DESC LIMIT $limit''',
                                {'tenant':self.tenant,'limit':min(100,max(1,limit))}).result_set
        return [self._decode(row[0]) for row in rows]
