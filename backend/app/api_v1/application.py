from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.event_ledger_service import EventLedgerService

_SECRET_TOKENS = ("password", "secret", "token", "private_key", "session_cookie", "credential")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(json.dumps(p, sort_keys=True, default=str) if not isinstance(p, str) else p for p in parts)
    return prefix + hashlib.sha256(raw.encode()).hexdigest()[:20].upper()


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not any(t in k.lower() for t in _SECRET_TOKENS)}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def node_visible(node: dict[str, Any] | None, as_of: str | None) -> bool:
    if not node:
        return False
    if as_of is None:
        return node.get("valid_until") is None
    point = to_epoch_us(as_of)
    for key in ("created_at", "observed_at", "occurred_at", "valid_from"):
        if node.get(key) is not None and to_epoch_us(node[key]) > point:
            return False
    if node.get("valid_until") is not None and to_epoch_us(node["valid_until"]) <= point:
        return False
    return True


def encode_cursor(entity_id: str) -> str:
    return base64.urlsafe_b64encode(entity_id.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    try:
        return base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode()
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc


class ExternalApiApplication:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def snapshot(self) -> GraphSnapshot:
        return GraphSnapshot.load(self.client)

    def get_node(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        node = self.snapshot().node(entity_id)
        return sanitize(node) if node_visible(node, as_of) else None

    def page(self, *, labels: set[str] | None = None, status: str | None = None, search: str | None = None, filters: dict[str, Any] | None = None, as_of: str | None = None, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        snap = self.snapshot(); after = decode_cursor(cursor); filters = filters or {}
        values=[]
        needle=(search or "").strip().casefold()
        # Match incident fields and directly related systems/teams/projects. Query before
        # pagination so matches are neither silently lost nor limited to the current page.
        searchable=("id", "name", "title", "description", "summary", "display_name")
        for node in snap.nodes.values():
            if not node_visible(node, as_of): continue
            if labels and not (set(node.get("_labels") or []) & labels): continue
            if status and str(node.get("status") or "").upper()!=status.upper(): continue
            if any(v is not None and str(node.get(k) or "") != str(v) for k,v in filters.items()): continue
            if needle:
                direct=any(needle in str(node.get(k) or "").casefold() for k in searchable)
                related=False
                if not direct and labels=={"Incident"}:
                    for other_id, _edge, _direction in snap.neighbors(str(node.get("id")), direction="both", as_of=as_of):
                        other=snap.node(other_id)
                        if not node_visible(other, as_of): continue
                        if set(other.get("_labels") or []) & {"System", "Team", "Project"}:
                            if any(needle in str(other.get(k) or "").casefold() for k in searchable):
                                related=True; break
                if not direct and not related: continue
            values.append(sanitize(node))
        values.sort(key=lambda x:str(x.get("id") or ""))
        if after:
            values=[v for v in values if str(v.get("id") or "")>after]
        chunk=values[:limit+1]; more=len(chunk)>limit; items=chunk[:limit]
        return {"items":items,"next_cursor":encode_cursor(str(items[-1]["id"])) if more and items else None,"has_more":more,"limit":limit}

    def create_situation(self, payload: dict[str, Any], *, subject: str, idempotency_key: str | None = None) -> dict[str, Any]:
        sid = payload.get("situation_id") or (stable_id("INC-API-", self.client.settings.tenant_id, idempotency_key) if idempotency_key else f"INC-API-{uuid.uuid4().hex[:12].upper()}")
        existing=self.get_node(sid)
        if existing:return existing
        at=payload.get("occurred_at") or now_iso()
        props={"name":payload["name"],"description":payload.get("description") or "","severity":payload.get("severity") or "MEDIUM","status":"OPEN","occurred_at":at,"created_at":now_iso(),"created_by":subject,"source":"external_api"}
        upsert_node(self.client,"Incident",sid,props)
        EventLedgerService(self.client).record("SITUATION_CREATED",about_ids=[sid],actor_id=None,summary=f"Situation created through external API by {subject}",event_id=stable_id("EVT-API-","SITUATION_CREATED",sid,idempotency_key or sid),properties={"phase":"11","api_subject":subject})
        return self.get_node(sid) or {"id":sid,**props}

    def create_investigation(self, payload: dict[str, Any], *, subject: str, idempotency_key: str | None = None) -> dict[str, Any]:
        snap=self.snapshot(); situation_id=payload["situation_id"]
        if situation_id not in snap.nodes:return {"error":"SITUATION_NOT_FOUND"}
        iid=stable_id("INV-API-",self.client.settings.tenant_id,idempotency_key or uuid.uuid4().hex,payload["question"],situation_id)
        at=now_iso(); props={"question":payload["question"],"status":"OPEN","created_at":at,"created_by":subject,"as_of":payload.get("as_of"),"seed_entity_ids_csv":",".join(payload.get("seed_entity_ids") or [situation_id])}
        upsert_node(self.client,"Investigation",iid,props)
        upsert_relationship(self.client,iid,"ABOUT",situation_id,{"valid_from":at,"edge_id":stable_id("EDGE-API-",iid,"ABOUT",situation_id)})
        EventLedgerService(self.client).record("INVESTIGATION_CREATED",about_ids=[iid,situation_id],summary=f"Investigation created through external API by {subject}",event_id=stable_id("EVT-API-","INVESTIGATION_CREATED",iid),properties={"phase":"11","api_subject":subject})
        return self.get_node(iid) or {"id":iid,**props}

    def close_investigation(self, investigation_id: str, *, subject: str) -> dict[str, Any] | None:
        current=self.get_node(investigation_id)
        if current is None or not has_label(current,"Investigation"):return None
        at=now_iso(); props={k:v for k,v in current.items() if not k.startswith("_") and k not in {"id","tenant_id"}}
        props.update({"status":"CLOSED","closed_at":at,"closed_by":subject})
        upsert_node(self.client,"Investigation",investigation_id,props)
        return self.get_node(investigation_id)

    def investigation_links(self, investigation_id: str, labels: set[str], rels: set[str] | None = None) -> list[dict[str, Any]]:
        snap=self.snapshot()
        if investigation_id not in snap.nodes:return []
        ids=set()
        for entity, edge, _ in snap.neighbors(investigation_id, rels, direction="both"):
            if set((snap.node(entity) or {}).get("_labels") or []) & labels:ids.add(entity)
        return [sanitize(snap.node(i)) for i in sorted(ids) if snap.node(i)]

    def relationships(self, entity_id: str, *, as_of: str | None = None, rel_types: set[str] | None = None) -> list[dict[str, Any]]:
        snap=self.snapshot(); out=[]
        if entity_id not in snap.nodes:return out
        for neighbor, edge, direction in snap.neighbors(entity_id, rel_types, direction="both", as_of=as_of):
            out.append({"direction":direction,"relationship":edge.type,"source":edge.source,"target":edge.target,"properties":sanitize(edge.properties),"neighbor":sanitize(snap.node(neighbor))})
        return out

    def provenance_summary(self, entity_id: str) -> dict[str, Any]:
        snap=self.snapshot(); node=snap.node(entity_id)
        if not node:return {}
        links=[]
        for nid,e,d in snap.neighbors(entity_id,{"DERIVED_FROM","NORMALIZED_TO","REFERENCES","RESOLVES_TO","INGESTED","FROM_SOURCE"},direction="both"):
            links.append({"direction":d,"relationship":e.type,"entity_id":nid,"entity_labels":(snap.node(nid) or {}).get("_labels",[])})
        return {"entity_id":entity_id,"source_ref_id":node.get("source_ref_id"),"source_record_id":node.get("source_record_id"),"links":links[:100]}
