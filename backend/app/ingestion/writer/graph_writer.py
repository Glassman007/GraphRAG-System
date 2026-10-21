from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.ingestion.models import ArtifactMetadata, NormalizedRecord, ResolutionDecision, SourceConfig, SourceRecordEnvelope, TrustClass
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService
from backend.app.services.memory_promotion_service import MemoryPromotionService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import csv, csv_list, now_iso, stable_id


class IngestionGraphWriter:
    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.promotion = MemoryPromotionService(client)
        self.invalidation = KnowledgeInvalidationService(client)

    def _relationship_props(self, *, config: SourceConfig, run_id: str, source_record_id: str, record: SourceRecordEnvelope, normalized: NormalizedRecord, candidate_props: dict[str, Any], confidence: float) -> dict[str, Any]:
        return {
            **candidate_props,
            "source_ref_id": config.id,
            "source_record_id": source_record_id,
            "source_record_ids_csv": source_record_id,
            "ingestion_run_id": run_id,
            "observed_at": record.observed_at,
            "valid_from": candidate_props.get("valid_from") or record.observed_at or record.source_updated_at or record.fetched_at,
            "confidence": confidence,
            "authority": config.trust_class.value,
            "authoritative": config.trust_class == TrustClass.AUTHORITATIVE,
            "mapping_rule": normalized.mapping_rule,
            "mapping_version": normalized.mapping_version,
        }

    def _upsert_canonical_relationship(self, source_id: str, rel_type: str, target_id: str, props: dict[str, Any], *, source_record_id: str) -> None:
        snapshot = GraphSnapshot.load(self.client)
        existing = [e for e in snapshot.edges_from(source_id, {rel_type}) if e.target == target_id and e.properties.get("valid_until") is None]
        if existing:
            edge = existing[0]
            refs = set(csv_list(edge.properties.get("source_record_ids_csv")))
            if edge.properties.get("source_record_id"):
                refs.add(str(edge.properties.get("source_record_id")))
            refs.add(source_record_id)
            merged = dict(edge.properties)
            merged.update({k: v for k, v in props.items() if v is not None and k not in {"source_ref_id"}})
            merged["source_record_ids_csv"] = csv(refs)
            merged["edge_id"] = edge.properties.get("edge_id")
            upsert_relationship(self.client, source_id, rel_type, target_id, merged)
            return
        props = dict(props)
        props["edge_id"] = stable_id("INGREL-", source_id, rel_type, target_id, str(props.get("valid_from") or "current"), length=24)
        upsert_relationship(self.client, source_id, rel_type, target_id, props)


    def _write_structural_assertion_claim(self, *, config: SourceConfig, source_record_id: str, actor_id: str, rel_type: str, target_id: str, observed_at: str) -> str:
        claim_id = stable_id("CLAIM-ING-STRUCT-", source_record_id, actor_id, rel_type, target_id, length=20)
        statement = f"{actor_id} {rel_type} {target_id}"
        upsert_node(self.client, "Claim", claim_id, {
            "name": statement, "statement": statement, "status": "UNVERIFIED", "confidence": 0.8,
            "assertion_kind": "external_structural_assertion", "source_ref_id": config.id,
            "source_record_id": source_record_id, "fact_source_id": actor_id,
            "fact_target_id": target_id, "fact_rel_type": rel_type,
            "created_at": observed_at, "valid_from": observed_at, "phase": "9",
        })
        evidence_id = stable_id("E-ING-STRUCT-", source_record_id, rel_type, target_id, length=20)
        upsert_node(self.client, "Evidence", evidence_id, {
            "name": f"External source assertion for {rel_type}", "evidence_type": "external_source_record",
            "status": "OBSERVED", "confidence": 0.9, "source_ref_id": config.id,
            "observed_at": observed_at, "created_at": now_iso(), "phase": "9",
        })
        upsert_relationship(self.client, evidence_id, "DERIVED_FROM", source_record_id, {"valid_from": observed_at, "confidence": 1.0, "source_ref_id": config.id})
        upsert_relationship(self.client, evidence_id, "SUPPORTS", claim_id, {"valid_from": observed_at, "confidence": 0.9, "source_ref_id": config.id})
        upsert_relationship(self.client, claim_id, "ABOUT", target_id, {"valid_from": observed_at, "confidence": 1.0, "source_ref_id": config.id})

        # Feed source disagreement into the existing Company Brain conflict model.
        # Claims conflict only when they assert the same structural predicate about
        # the same target but name different source actors.  Name similarity or
        # merely sharing a subject is insufficient.
        snapshot = GraphSnapshot.load(self.client)
        for other in snapshot.nodes.values():
            if not has_label(other, "Claim") or str(other.get("id")) == claim_id:
                continue
            if other.get("assertion_kind") != "external_structural_assertion":
                continue
            if other.get("fact_rel_type") != rel_type or other.get("fact_target_id") != target_id:
                continue
            other_actor = str(other.get("fact_source_id") or "")
            if not other_actor or other_actor == actor_id:
                continue
            other_id = str(other["id"])
            upsert_relationship(self.client, claim_id, "CONTRADICTS", other_id, {
                "detected_at": observed_at,
                "valid_from": observed_at,
                "confidence": min(float(other.get("confidence") or 0.8), 0.8),
                "reason": "conflicting_external_structural_assertions",
                "source_ref_id": config.id,
            })
        return claim_id

    def _validated_source_evidence(self, *, source_record_id: str, source_id: str, subject_id: str, fact_type: str, observed_at: str) -> str:
        evidence_id = stable_id("E-ING-AUTH-", source_record_id, fact_type, subject_id, length=20)
        upsert_node(self.client, "Evidence", evidence_id, {
            "name": f"Authoritative external {fact_type} assertion",
            "evidence_type": "external_authoritative_fact",
            "status": "VALIDATED",
            "confidence": 1.0,
            "source_authority": 1.0,
            "source_ref_id": source_id,
            "observed_at": observed_at,
            "created_at": now_iso(),
            "phase": "9",
        })
        upsert_relationship(self.client, evidence_id, "DERIVED_FROM", source_record_id, {"valid_from": now_iso(), "confidence": 1.0, "source_ref_id": source_id})
        upsert_relationship(self.client, evidence_id, "VALIDATED_BY", source_id, {"valid_from": now_iso(), "confidence": 1.0, "source_ref_id": source_id})
        upsert_relationship(self.client, evidence_id, "ABOUT", subject_id, {"valid_from": now_iso(), "confidence": 1.0, "source_ref_id": source_id})
        return evidence_id

    def write(self, *, config: SourceConfig, run_id: str, source_record_id: str, record: SourceRecordEnvelope, normalized: NormalizedRecord, resolutions: list[ResolutionDecision], artifacts: list[ArtifactMetadata] | None = None) -> dict[str, Any]:
        resolution_map = {x.entity_key: x for x in resolutions}
        entity_map: dict[str, str] = {}
        written_nodes: list[str] = []
        written_relationships: list[str] = []
        warnings: list[str] = []

        for entity in normalized.entities:
            decision = resolution_map.get(entity.key)
            if decision is None or not decision.canonical_id:
                warnings.append(f"UNRESOLVED_ENTITY:{entity.key}")
                continue
            cid = decision.canonical_id
            entity_map[entity.key] = cid
            # Newly created/non-identity entities receive normalized content. Existing identity nodes
            # are not blindly overwritten by lower-trust source fields.
            existing = None if entity.ontology_type in {"SqlTable", "SqlColumn", "SqlConstraint"} else GraphSnapshot.load(self.client).node(cid)
            if existing is None or decision.status.value == "CREATED" or not entity.requires_resolution:
                props = dict(entity.properties)
                props.setdefault("created_at", record.observed_at or record.fetched_at)
                props["last_ingested_at"] = now_iso()
                props["source_ref_id"] = config.id
                props["source_record_id"] = source_record_id
                props["mapping_rule"] = normalized.mapping_rule
                upsert_node(self.client, entity.ontology_type, cid, props)
                written_nodes.append(cid)

            # SourceRecord -> canonical lineage is a Phase 9 invariant, not an
            # incidental side effect of identity resolution.  Keep the edge
            # deterministic so full resyncs update/reuse it rather than create
            # parallel provenance edges.  Tombstone handling relies on this
            # lineage to identify affected canonical entities without deleting
            # them.
            upsert_relationship(self.client, source_record_id, "NORMALIZED_TO", cid, {
                "edge_id": stable_id("ING-NORM-", self.client.settings.tenant_id, source_record_id, cid, normalized.mapping_rule, length=24),
                "valid_from": record.observed_at or record.fetched_at,
                "confidence": decision.confidence,
                "source_ref_id": config.id,
                "mapping_rule": normalized.mapping_rule,
            })

        for rel in normalized.relations:
            sid, tid = entity_map.get(rel.source_key), entity_map.get(rel.target_key)
            if not sid or not tid:
                warnings.append(f"RELATION_ENDPOINT_UNRESOLVED:{rel.source_key}:{rel.rel_type}:{rel.target_key}")
                continue
            if rel.requires_authoritative_source and config.trust_class != TrustClass.AUTHORITATIVE:
                warnings.append(f"NON_AUTHORITATIVE_RELATION_SKIPPED:{sid}:{rel.rel_type}:{tid}")
                continue
            props = self._relationship_props(config=config, run_id=run_id, source_record_id=source_record_id, record=record, normalized=normalized, candidate_props=rel.properties, confidence=rel.confidence)
            if normalized.mapping_rule in {"github:sql_file", "database:database_schema"}:
                # The constraint identity separates distinct FKs between the same
                # pair of tables. MERGE reuses these edges on a repeated sync.
                props["edge_id"] = stable_id("ING-SQL-EDGE-", self.client.settings.tenant_id,
                                             sid, rel.rel_type, tid,
                                             str(rel.properties.get("constraint_id") or ""), length=24)
                upsert_relationship(self.client, sid, rel.rel_type, tid, props)
            elif rel.rel_type in {"OWNS", "RESPONSIBLE_FOR"} and config.trust_class == TrustClass.AUTHORITATIVE:
                if not bool(config.settings.get("auto_validate_ownership", False)):
                    claim_id = self._write_structural_assertion_claim(config=config, source_record_id=source_record_id, actor_id=sid, rel_type=rel.rel_type, target_id=tid, observed_at=record.observed_at or record.fetched_at)
                    warnings.append(f"STRUCTURAL_ASSERTION_REQUIRES_PHASE7_VALIDATION:{claim_id}")
                    upsert_relationship(self.client, source_record_id, "NORMALIZED_TO", claim_id, {"valid_from": record.fetched_at, "confidence": rel.confidence, "source_ref_id": config.id, "fact_source_id": sid, "fact_target_id": tid, "fact_rel_type": rel.rel_type, "mapping_rule": normalized.mapping_rule})
                    continue
                current = GraphSnapshot.load(self.client)
                same_active = [e for e in current.edges_from(sid, {rel.rel_type}) if e.target == tid and e.properties.get("valid_until") is None]
                if same_active:
                    self._upsert_canonical_relationship(sid, rel.rel_type, tid, props, source_record_id=source_record_id)
                else:
                    evidence_id = self._validated_source_evidence(source_record_id=source_record_id, source_id=config.id, subject_id=tid, fact_type=rel.rel_type, observed_at=record.observed_at or record.fetched_at)
                    result = self.promotion.promote_responsibility(actor_id=sid, resource_id=tid, relation_type=rel.rel_type, verification_id=evidence_id, authority_id=config.id, effective_at=str(props["valid_from"]))
                    if result.get("status") != "PROMOTED":
                        warnings.append(f"RESPONSIBILITY_PROMOTION_NOT_READY:{result.get('reasons')}")
                        continue
                    # Phase 7 owns the trust transition, but Phase 9 still owns
                    # source lineage. Enrich the promoted canonical edge with
                    # the exact SourceRecord that justified this promotion so
                    # later sources append rather than replacing provenance.
                    self._upsert_canonical_relationship(sid, rel.rel_type, tid, props, source_record_id=source_record_id)
            elif rel.rel_type == "DEPENDS_ON" and config.trust_class == TrustClass.AUTHORITATIVE and not bool(config.settings.get("auto_validate_dependencies", False)):
                claim_id = self._write_structural_assertion_claim(config=config, source_record_id=source_record_id, actor_id=sid, rel_type=rel.rel_type, target_id=tid, observed_at=record.observed_at or record.fetched_at)
                warnings.append(f"STRUCTURAL_ASSERTION_REQUIRES_PHASE7_VALIDATION:{claim_id}")
                continue
            else:
                before = GraphSnapshot.load(self.client)
                previous_active = [e for e in before.edges_from(sid, {rel.rel_type}) if e.target == tid and e.properties.get("valid_until") is None]
                self._upsert_canonical_relationship(sid, rel.rel_type, tid, props, source_record_id=source_record_id)
                if rel.rel_type == "DEPENDS_ON" and config.trust_class == TrustClass.AUTHORITATIVE and not previous_active:
                    self.invalidation.dependency_changed(sid, tid, change_type="ADDED", timestamp=str(props["valid_from"]))
            upsert_relationship(self.client, source_record_id, "NORMALIZED_TO", tid, {
                "edge_id": stable_id("ING-FACT-LINEAGE-", self.client.settings.tenant_id,
                                     source_record_id, sid, rel.rel_type, tid,
                                     str(rel.properties.get("constraint_id") or ""), length=24),
                "valid_from": record.fetched_at,
                "confidence": rel.confidence,
                "source_ref_id": config.id,
                "fact_source_id": sid,
                "fact_target_id": tid,
                "fact_rel_type": rel.rel_type,
                "mapping_rule": normalized.mapping_rule,
            })
            written_relationships.append(f"{sid}-[:{rel.rel_type}]->{tid}")

        for artifact in artifacts or []:
            for entity in normalized.entities:
                cid = entity_map.get(entity.key)
                if cid and entity.ontology_type in {"Evidence", "Document", "Policy", "Incident"}:
                    rel_type = "DERIVED_FROM" if entity.ontology_type in {"Evidence", "Document"} else "REFERENCES"
                    upsert_relationship(self.client, cid, rel_type, artifact.artifact_id, {
                        "edge_id": stable_id("ING-ENTITY-ARTIFACT-", self.client.settings.tenant_id,
                                             cid, rel_type, artifact.artifact_id, length=24),
                        "valid_from": artifact.created_at, "confidence": 1.0, "source_ref_id": config.id})

        return {"entity_map": entity_map, "written_nodes": sorted(set(written_nodes)), "written_relationships": written_relationships, "warnings": warnings}

    def write_tombstone(self, *, config: SourceConfig, run_id: str, source_record_id: str, record: SourceRecordEnvelope) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        source = snapshot.node(source_record_id) or {}
        source_key = source.get("source_key")
        previous_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_key") == source_key and n.get("id") != source_record_id]
        affected: set[str] = set()
        for prev in previous_records:
            for edge in snapshot.edges_from(str(prev["id"]), {"NORMALIZED_TO"}):
                affected.add(edge.target)
        evidence_id = stable_id("E-ING-TOMBSTONE-", source_record_id, length=20)
        upsert_node(self.client, "Evidence", evidence_id, {
            "name": f"Source tombstone {source.get('source_entity_id') or record.external_id}",
            "evidence_type": "source_tombstone",
            "status": "OBSERVED",
            "confidence": 1.0,
            "source_ref_id": config.id,
            "observed_at": record.observed_at or record.fetched_at,
            "created_at": record.fetched_at,
            "ingestion_run_id": run_id,
        })
        upsert_relationship(self.client, evidence_id, "DERIVED_FROM", source_record_id, {"valid_from": record.fetched_at, "confidence": 1.0, "source_ref_id": config.id})
        for target in sorted(affected):
            upsert_relationship(self.client, evidence_id, "ABOUT", target, {"valid_from": record.fetched_at, "confidence": 1.0, "source_ref_id": config.id})
        return {"tombstone_evidence_id": evidence_id, "affected_entities": sorted(affected), "canonical_deleted": False}
