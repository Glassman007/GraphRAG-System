"""Component 3: verified, scoped agent memory (NOT conversation transcript storage).

Working observations are private until a separate verification specialist validates
that claim against currently visible graph evidence. Only verified durable records
are reusable by a later session. No organizational business facts are mutated.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.app.agent_runtime.tools import current


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class MemorySearch(Strict):
    entity_ids: list[str] = Field(default_factory=list, max_length=15)
    query: str = Field(default='', max_length=250)
    limit: int = Field(default=8, ge=1, le=20)


class MemoryAssertion(Strict):
    subject_id: str = Field(min_length=2, max_length=150)
    predicate: str = Field(min_length=2, max_length=100)
    value: str = Field(min_length=1, max_length=300)
    citations: list[str] = Field(min_length=1, max_length=20)
    source_tools: list[str] = Field(default_factory=list, max_length=12)
    summary: str = Field(default='', max_length=1400)
    valid_until: str | None = None


class MemoryBackend(Protocol):
    def save(self, entry: dict) -> None: ...
    def get(self, memory_id: str) -> dict | None: ...
    def candidates(self, entity_ids: list[str], query: str, limit: int) -> list[dict]: ...
    def private_for_run(self, run_id: str, task_ids: list[str]) -> list[dict]: ...
    def conflicting(self, subject_id: str, predicate: str, value: str) -> list[dict]: ...


class AgentMemory:
    def __init__(self, *, backend: MemoryBackend, snapshot_factory: Callable, tenant: str):
        self.backend = backend
        self.snapshot_factory = snapshot_factory
        self.tenant = tenant
        self._lock = threading.RLock()

    def _source_ok(self, ids: list[str]) -> bool:
        if not ids:
            return False
        snapshot = self.snapshot_factory()
        return all(snapshot.node(cid) and current(snapshot.node(cid)) for cid in ids)

    def _fact_matches(self, record: dict) -> bool:
        """Deterministic verification of known canonical predicates against current graph.

        Arbitrary model-generated prose is not sufficient proof for promotion.
        """
        snapshot = self.snapshot_factory()
        subject = snapshot.node(record['subject_id'])
        if not subject or not current(subject):
            return False
        predicate = record['predicate'].casefold().strip().replace(' ', '_')
        value = record['value']
        if predicate in {'depends_on', 'dependency_on', 'dependency'}:
            return any(e.source == record['subject_id'] and e.target == value and
                       e.type == 'DEPENDS_ON' and snapshot._edge_active(e, None) and current(snapshot.node(e.target))
                       for e in snapshot.edges)
        allowed_properties = {'status', 'name', 'severity', 'criticality', 'owner_id', 'source_type'}
        return predicate in allowed_properties and str(subject.get(predicate) or '').casefold() == value.casefold()

    def stage(self, *, claim: MemoryAssertion, run_id: str, task_id: str,
              agent_id: str, owner: str, branch_id: str, observed_ids: set[str],
              confidence: str, goal: str, derived_memory_ids: list[str] | None = None) -> dict:
        """Never trust a specialist's free-text assertion as evidence by itself."""
        if confidence != 'supported':
            raise ValueError('Only source-supported assertions may be staged')
        if not set(claim.citations).issubset(observed_ids) or claim.subject_id not in observed_ids:
            raise ValueError('Memory source citations must have been observed by the specialist')
        if len(set(claim.citations)) != len(claim.citations) or not self._source_ok(claim.citations):
            raise ValueError('Memory citations must be distinct, current graph entities')
        if claim.valid_until and (parse_date(claim.valid_until) is None or parse_date(claim.valid_until) <= datetime.now(timezone.utc)):
            raise ValueError('Memory validity date is invalid or expired')
        result = {'id': 'MEM-' + uuid.uuid4().hex.upper(), 'tenant_id': self.tenant,
                  'scope': 'PRIVATE', 'status': 'DRAFT', 'subject_id': claim.subject_id,
                  'predicate': claim.predicate, 'value': claim.value, 'summary': claim.summary,
                  'citations': claim.citations, 'source_tools': claim.source_tools,
                  'derived_memory_ids': (derived_memory_ids or [])[:20],
                  'origin_run_id': run_id, 'origin_task_id': task_id, 'origin_agent_id': agent_id,
                  'owner': owner, 'branch_id': branch_id, 'verified_by': '',
                  'verified_at': '', 'created_at': utcnow(), 'updated_at': utcnow(),
                  'valid_until': claim.valid_until or '', 'superseded_by': '',
                  'goal_context': goal[:350], 'revision': 1, 'conflicts_with': []}
        with self._lock:
            self.backend.save(result)
        return result

    def consolidate(self, *, run_id: str, verifier_task_id: str, verifier_agent_id: str,
                    verifier_citations: list[str], verifier_assertions: list[dict], verifier_confidence: str,
                    verifier_conflicted: bool, review_required: bool,
                    task_ids: list[str], owner: str) -> list[dict]:
        """Promote only verified claims whose *actual citations* were rechecked.

        A verifier's generic approval cannot bless a claim it did not cite.
        Conflicting result sets are never auto-published.
        """
        if (verifier_confidence != 'supported' or verifier_conflicted or review_required or
                verifier_agent_id not in {'policy_verifier', 'independent_verifier'}):
            return []
        if not self._source_ok(verifier_citations):
            return []
        promoted = []
        for candidate in self.backend.private_for_run(run_id, task_ids):
            if candidate.get('tenant_id') != self.tenant or candidate.get('owner') != owner:
                continue
            if candidate.get('status') != 'DRAFT' or candidate.get('scope') != 'PRIVATE':
                continue
            if not set(candidate['citations']).issubset(set(verifier_citations)):
                continue
            # The verifier must explicitly corroborate the same proposition, not merely see an ID.
            if not any(a.get('subject_id') == candidate['subject_id'] and
                       a.get('predicate', '').casefold() == candidate['predicate'].casefold() and
                       a.get('value', '').casefold() == candidate['value'].casefold()
                       for a in verifier_assertions):
                continue
            try:
                promoted.append(self.verify(candidate['id'], verifier_agent_id=verifier_agent_id,
                                            verifier_task_id=verifier_task_id,
                                            checked_citations=verifier_citations, owner=owner))
            except ValueError:
                # Unsupported or stale propositions remain private; never publish them.
                continue
        return promoted

    def verify(self, memory_id: str, *, verifier_agent_id: str, verifier_task_id: str,
               checked_citations: list[str], owner: str) -> dict:
        """One guarded promotion; conflicts quarantine the candidate, not previous truth.

        The verified identity is (tenant, subject, predicate). Different values
        cannot auto-overwrite; a human explicitly invalidates old entries first.
        """
        if verifier_agent_id not in {'policy_verifier', 'independent_verifier'}:
            raise PermissionError('Independent verification specialist required')
        with self._lock:
            record = self.backend.get(memory_id)
            if not record or record.get('tenant_id') != self.tenant or record.get('owner') != owner:
                raise PermissionError('Memory not found or inaccessible')
            if record['status'] != 'DRAFT' or record['scope'] != 'PRIVATE':
                raise ValueError('Only private draft claims can be promoted')
            if record['origin_task_id'] == verifier_task_id:
                raise ValueError('Self-verification is forbidden')
            if not set(record['citations']).issubset(set(checked_citations)) or not self._source_ok(record['citations']) or not self._fact_matches(record):
                raise ValueError('Verifier did not validate the current cited evidence')
            # Dedicated exact-identity lookup: never miss an old conflict because
            # a general-purpose retrieval scan was bounded to recent results.
            conflicts = [p for p in self.backend.conflicting(record['subject_id'],
                         record['predicate'], record['value'])
                         if p.get('tenant_id') == self.tenant]
            if conflicts:
                record.update(status='CONFLICT', conflicts_with=[p['id'] for p in conflicts], updated_at=utcnow(),
                              revision=int(record['revision']) + 1)
            else:
                record.update(status='VERIFIED', scope='SHARED', verified_by=verifier_agent_id,
                              verified_at=utcnow(), updated_at=utcnow(), revision=int(record['revision']) + 1)
            self.backend.save(record)
            return record

    def retrieve(self, *, requester: str, agent_id: str, permissions: frozenset[str],
                 search: MemorySearch, run_id: str | None = None, branch_id: str | None = None) -> list[dict]:
        if not {'READ_GRAPH', 'READ_EVIDENCE'}.issubset(permissions):
            raise PermissionError('Graph and evidence read permissions required')
        snapshot = self.snapshot_factory()
        # Context expansion: direct entities plus one-hop neighbors, staying within tenant snapshot.
        entities = set(search.entity_ids)
        for entity in list(entities):
            if snapshot.node(entity):
                for other, _edge, _direction in snapshot.neighbors(entity):
                    if len(entities) < 55:
                        entities.add(other)
        hits = []
        for record in self.backend.candidates(sorted(entities), search.query, 250):
            if record.get('tenant_id') != self.tenant:
                continue
            shared = record.get('scope') == 'SHARED' and record.get('status') == 'VERIFIED'
            private = (record.get('scope') == 'PRIVATE' and record.get('status') == 'DRAFT'
                       and record.get('owner') == requester and record.get('origin_agent_id') == agent_id
                       and record.get('origin_run_id') == run_id and record.get('branch_id') == branch_id)
            if not shared and not private:
                continue
            if not self._source_ok(record.get('citations') or []) or not self._fact_matches(record):
                continue
            expires = parse_date(record.get('valid_until'))
            if expires and expires <= datetime.now(timezone.utc):
                continue
            checked = parse_date(record.get('verified_at'))
            if shared and (checked is None or checked + timedelta(days=30) <= datetime.now(timezone.utc)):
                continue  # automatic recheck required before reuse
            # No arbitrary text-only recalls: tie results to requested entities or a contextual term.
            query_terms = set(re.findall(r'[a-z0-9]{3,}', search.query.lower()))
            text = ' '.join(str(record.get(k) or '') for k in ('subject_id', 'predicate', 'value', 'summary', 'goal_context')).lower()
            relation_match = record['subject_id'] in entities or bool(set(record.get('citations') or []) & entities)
            text_match = bool(query_terms and any(word in text for word in query_terms))
            if search.entity_ids and not relation_match and not text_match:
                continue
            if not search.entity_ids and not text_match:
                continue
            item = {k: v for k, v in record.items() if k not in {'owner', 'branch_id', 'goal_context'}}
            item['relevance'] = (3 if record['subject_id'] in search.entity_ids else 0) + (2 if relation_match else 0) + int(text_match)
            hits.append(item)
        hits.sort(key=lambda x: (-x['relevance'], x.get('verified_at') or x.get('created_at') or ''), reverse=False)
        return hits[:search.limit]

    def set_validity(self, memory_id: str, *, actor: str, permission: frozenset[str],
                     status: str, reason: str) -> dict:
        if 'CREATE_INVESTIGATION' not in permission:
            raise PermissionError('Review permission required')
        if status not in {'INVALIDATED', 'SUPERSEDED', 'RECHECK_REQUIRED'} or len(reason.strip()) < 10:
            raise ValueError('Invalid status or review rationale')
        with self._lock:
            record = self.backend.get(memory_id)
            if not record or record.get('tenant_id') != self.tenant:
                raise PermissionError('Memory not found or inaccessible')
            if record['status'] != 'VERIFIED' or record['scope'] != 'SHARED':
                raise ValueError('Only shared verified knowledge can be reviewed')
            record.update(status=status, scope='PRIVATE', updated_at=utcnow(),
                          review_reason=reason[:500], reviewed_by=actor,
                          revision=int(record['revision']) + 1)
            self.backend.save(record)
            return record
