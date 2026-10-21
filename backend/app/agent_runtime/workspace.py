"""Component 6: live *observable* workspace for the existing bounded supervisor.

Only graph-persisted operational state is presented. No model private reasoning is
exposed. Background execution is process-local (single API worker supported);
checkpoints and workspace records are durable in FalkorDB for explicit recovery.
No external business operations are dispatched by this service.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Any
from pydantic import BaseModel, ConfigDict, Field

from backend.app.agent_runtime.supervisor import SupervisorSettings
from backend.app.services.phase3_utils import node_dict


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str = Field(min_length=12, max_length=1500)
    graph_id: str | None = Field(default=None, min_length=1, max_length=96)
    source_entity_id: str | None = Field(default=None, min_length=3, max_length=150)
    max_parallel: int = Field(default=3, ge=1, le=4)
    allow_external_model: bool = False

    def settings(self) -> SupervisorSettings:
        return SupervisorSettings(goal=self.goal, source_entity_id=self.source_entity_id,
                                  max_parallel=self.max_parallel, allow_external_model=self.allow_external_model)


class WorkspaceStore:
    """Tenant-scoped record, control commands and replay snapshots in the memory graph.

    Single-worker coordination only: this lock is not a distributed worker lease.
    """
    def __init__(self, client):
        self.tenant = client.settings.tenant_id
        self.graph = client.db.select_graph(client.settings.falkordb_graph + '_agent_memory')
        self.lock = _workspace_record_lock

    @staticmethod
    def _decode(node) -> dict:
        try:
            return json.loads((node_dict(node) or {}).get('document_json') or '{}')
        except (ValueError, TypeError):
            return {}

    def create(self, record: dict) -> None:
        if record['tenant'] != self.tenant or not re.fullmatch(r'SRUN-[A-F0-9]{32}', record['id']):
            raise PermissionError('Tenant or run ID invalid')
        with self.lock:
            self.graph.query('''CREATE (w:AgentWorkspaceRun {tenant_id:$tenant,id:$id,
                owner:$owner,status:$status,created_at:$created,document_json:$document})''',
                {'tenant': self.tenant, 'id': record['id'], 'owner': record['owner'],
                 'status': record['status'], 'created': record['created_at'],
                 'document': json.dumps(record)})

    def get(self, run_id: str, owner: str) -> dict | None:
        rows = self.graph.ro_query('''MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,id:$id,owner:$owner})
            RETURN w LIMIT 1''', {'tenant':self.tenant,'id':run_id,'owner':owner}).result_set
        return self._decode(rows[0][0]) if rows else None

    def list(self, owner: str, limit: int = 30) -> list[dict]:
        rows = self.graph.ro_query('''MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,owner:$owner})
             RETURN w ORDER BY w.created_at DESC LIMIT $limit''',
            {'tenant':self.tenant,'owner':owner,'limit':min(max(limit,1),100)}).result_set
        return [self._decode(r[0]) for r in rows]

    def update(self, run_id: str, owner: str, *, status: str | None = None,
               command: str | None = None, error: str | None = None) -> dict:
        with self.lock:
            entry = self.get(run_id, owner)
            if not entry:
                raise KeyError('Owned workspace run not found')
            if status is not None:
                entry['status'] = status
            if command is not None:
                entry['command'] = command
            if error is not None:
                entry['error'] = error[:300]
            entry['updated_at'] = now()
            self.graph.query('''MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,id:$id,owner:$owner})
                SET w.status=$status,w.document_json=$document''',
                {'tenant':self.tenant,'id':run_id,'owner':owner,
                 'status':entry['status'],'document':json.dumps(entry)})
            return entry

    def capture(self, run_id: str, owner: str, summary: dict) -> None:
        if not self.get(run_id, owner):
            raise KeyError('Owned workspace run not found')
        with self.lock:
            self.graph.query('''MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,id:$run,owner:$owner})
               CREATE (s:AgentWorkspaceSnapshot {tenant_id:$tenant,id:$id,
                 run_id:$run,owner:$owner,created_at:$at,document_json:$data})
               CREATE (w)-[:HAS_WORKSPACE_SNAPSHOT]->(s)''',
               {'tenant':self.tenant,'run':run_id,'owner':owner,
                'id':'WSNAP-'+uuid.uuid4().hex.upper(),'at':now(),
                'data':json.dumps(summary)})

    def snapshots(self, run_id: str, owner: str, limit: int = 8) -> list[dict]:
        rows = self.graph.ro_query('''MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,id:$run,owner:$owner})
            -[:HAS_WORKSPACE_SNAPSHOT]->(s:AgentWorkspaceSnapshot {tenant_id:$tenant})
            RETURN s ORDER BY s.created_at DESC LIMIT $limit''',
            {'tenant':self.tenant,'run':run_id,'owner':owner,'limit':limit}).result_set
        return list(reversed([self._decode(r[0]) for r in rows]))


_workspace_record_lock = threading.RLock()


class WorkspaceRunner:
    """Limited in-process background worker; not an at-least-once distributed queue."""
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='gh-workspace')
        self.futures: dict[tuple[str, str], Future] = {}
        self.lock = threading.RLock()

    def live(self, tenant: str, run_id: str) -> bool:
        with self.lock:
            future = self.futures.get((tenant,run_id))
            return bool(future and not future.done())

    def submit(self, *, tenant: str, run_id: str, execute: Callable[[], None]) -> None:
        with self.lock:
            key = (tenant,run_id)
            existing = self.futures.get(key)
            if existing and not existing.done():
                raise ValueError('Run already has an active worker')
            if sum(not task.done() for task in self.futures.values()) >= 2:
                raise ValueError('Workspace worker capacity is exhausted (maximum 2 active runs)')
            future = self.pool.submit(execute)
            self.futures[key] = future


runner = WorkspaceRunner()


def format_workspace(record: dict, *, is_live: bool) -> dict:
    """Make restart ambiguity explicit instead of implying an active worker exists."""
    result = dict(record)
    if result['status'] in {'QUEUED','RUNNING','PAUSING','CANCELLING'} and not is_live:
        result['status'] = 'INTERRUPTED'
        result['recovery_available'] = True
    else:
        result['recovery_available'] = result['status'] in {'PAUSED','INTERRUPTED','FAILED','PARTIAL','NEEDS_REVIEW'}
    result['execution_mode'] = 'LIVE_MODEL' if record.get('allow_external_model') else 'UNSUPPORTED'
    result['side_effects'] = 'NONE_READ_ONLY'
    return result


def build_replay(supervisor: dict | None, checkpoint: dict | None) -> dict:
    """Reconstruct a bounded, time-ordered operational timeline, never hidden reasoning."""
    events = list((supervisor or {}).get('events') or (checkpoint or {}).get('events') or [])
    events.sort(key=lambda e: (int(e.get('event_index', e.get('index', 0))), str(e.get('created_at',''))))
    tasks = (supervisor or {}).get('tasks') or (checkpoint or {}).get('tasks') or []
    return {'events':events, 'tasks':tasks,
            'checkpoints': {'revision':(checkpoint or {}).get('revision'),
                            'status':(checkpoint or {}).get('status'),
                            'updated_at':(checkpoint or {}).get('updated_at')},
            'limitations': 'Operational event replay; not private model reasoning or full graph snapshot replay.'}


def task_comparison(checkpoint: dict | None, supervisor: dict | None) -> list[dict]:
    """Compare checkpointed task state to the latest graph record when both exist."""
    before = {t['id']:t for t in (checkpoint or {}).get('tasks',[]) if 'id' in t}
    after = {t['task_id'] if 'task_id' in t else t['id']:t for t in (supervisor or {}).get('tasks',[]) if 'id' in t}
    return [{'task_id':task, 'checkpoint_status':before.get(task,{}).get('status'),
             'current_status':after.get(task,{}).get('status')}
            for task in sorted(before.keys()|after.keys())
            if before.get(task,{}).get('status') != after.get(task,{}).get('status')]
