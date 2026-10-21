from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.agent_runtime.reactive import ReactiveLearning, graph_delta
from backend.app.agent_runtime.reactive_store import GraphReactiveStore
from backend.app.agent_runtime.memory import AgentMemory
from backend.app.agent_runtime.memory_store import GraphMemoryStore
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import IngestionReport, IngestionRunStatus, ProposedMutation, ResolutionStatus
from backend.app.ingestion.normalization.mappings import normalizer_for
from backend.app.ingestion.provenance.service import IngestionProvenanceService
from backend.app.ingestion.registry import SourceRegistry, build_default_registry
from backend.app.ingestion.resolution.service import IngestionEntityResolutionService
from backend.app.ingestion.writer.graph_writer import IngestionGraphWriter
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id


class IngestionPipeline:
    def __init__(
        self,
        client: FalkorGraphClient,
        *,
        registry: SourceRegistry | None = None,
        artifact_store: LocalArtifactStore | None = None,
        root: Path | None = None,
        retrieval_indexer: Any | None = None,
    ):
        self.client = client
        self.root = root or Path(__file__).resolve().parents[3]
        self.registry = registry or build_default_registry(client, root=self.root, persist=False)
        artifact_root = os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or str(self.root / ".graphhacks_artifacts")
        threshold = int(os.getenv("GRAPH_HACKS_ARTIFACT_THRESHOLD_BYTES", "16384"))
        self.artifacts = artifact_store or LocalArtifactStore(artifact_root, inline_threshold_bytes=threshold)
        self.provenance = IngestionProvenanceService(client)
        self.resolution = IngestionEntityResolutionService(client)
        self.writer = IngestionGraphWriter(client)
        self.events = EventLedgerService(client)
        self._reactive = None  # Do not touch FalkorDB on dry-run or metadata-only reads.
        self.retrieval_indexer = retrieval_indexer

    @property
    def reactive(self) -> ReactiveLearning:
        if self._reactive is None:
            client = self.client
            self._reactive = ReactiveLearning(store=GraphReactiveStore(client),
                memory=AgentMemory(backend=GraphMemoryStore(client),
                                   snapshot_factory=lambda: GraphSnapshot.load(client),
                                   tenant=client.settings.tenant_id),
                snapshot_factory=lambda: GraphSnapshot.load(client), tenant=client.settings.tenant_id)
        return self._reactive

    def _source_cursor(self, source_id: str) -> str | None:
        node = GraphSnapshot.load(self.client).node(source_id)
        return str(node.get("last_successful_cursor")) if node and node.get("last_successful_cursor") is not None else None

    def _advance_cursor(self, source_id: str, cursor: str | None) -> None:
        if cursor is None:
            return
        upsert_node(self.client, "DataSource", source_id, {"last_successful_cursor": cursor, "last_sync_at": now_iso()})

    def _quarantine_unmapped(self, source_record_id: str, source_id: str, reason: str) -> None:
        qid = stable_id("QUAR-", source_record_id, reason, length=20)
        at = now_iso()
        upsert_node(self.client, "IngestionQuarantineRecord", qid, {
            "name": f"Quarantine {source_record_id}", "source_record_id": source_record_id, "status": "OPEN",
            "reason": reason, "created_at": at, "source_ref_id": source_id,
        })
        upsert_relationship(self.client, qid, "DERIVED_FROM", source_record_id, {"valid_from": at, "confidence": 1.0, "source_ref_id": source_id})

    def _dry_run_record(self, config, record, source_record_id: str, normalized) -> tuple[list[ProposedMutation], int, int]:
        proposed: list[ProposedMutation] = []
        resolved = 0
        quarantined = 0
        mapping: dict[str, str] = {}
        for entity in normalized.entities:
            decision = self.resolution.preview(entity, config)
            if decision.canonical_id:
                mapping[entity.key] = decision.canonical_id
                resolved += 1
                proposed.append(ProposedMutation(kind="node", label_or_type=entity.ontology_type, entity_id=decision.canonical_id, properties={"resolution_status": decision.status.value, **entity.properties}))
            else:
                quarantined += 1
        for rel in normalized.relations:
            if rel.source_key in mapping and rel.target_key in mapping:
                if rel.requires_authoritative_source and config.trust_class.value != "AUTHORITATIVE":
                    continue
                proposed.append(ProposedMutation(kind="relationship", label_or_type=rel.rel_type, source_id=mapping[rel.source_key], target_id=mapping[rel.target_key], properties=rel.properties))
        return proposed, resolved, quarantined

    def sync(
        self,
        source_id: str,
        *,
        mode: str = "incremental",
        max_records: int = 100,
        batch_size: int = 50,
        dry_run: bool = False,
        fail_after_committed: int | None = None,
    ) -> IngestionReport:
        if mode not in {"incremental", "full"}:
            raise ValueError("mode must be 'incremental' or 'full'")
        if max_records < 1 or max_records > 10_000:
            raise ValueError("max_records must be between 1 and 10000")
        if batch_size < 1 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        try:
            config, adapter = self.registry.get(source_id)
        except KeyError as exc:
            raise ValueError(f"Unknown ingestion source: {source_id}") from exc
        if not config.enabled:
            raise ValueError(f"Ingestion source is disabled: {source_id}")
        normalizer = normalizer_for(config)
        cursor_start = self._source_cursor(source_id) if mode == "incremental" else None
        cursor = cursor_start
        run_id = stable_id("INGRUN-DRY-", source_id, now_iso(), length=20) if dry_run else ""
        report = IngestionReport(run_id=run_id or "pending", source_id=source_id, status=IngestionRunStatus.DRY_RUN if dry_run else IngestionRunStatus.RUNNING, cursor_start=cursor_start)

        if not dry_run:
            self.registry.persist_source(config)
            run_id = self.provenance.create_run(config, cursor_start=cursor_start)
            report.run_id = run_id
            self.events.record("INGESTION_RUN_STARTED", about_ids=[run_id, source_id], summary=f"Started ingestion from {source_id}", event_id=stable_id("EVT-P9-", "INGESTION_RUN_STARTED", run_id), properties={"phase": "9", "source_ref_id": source_id})

        processed = 0
        try:
            while processed < max_records:
                page = adapter.fetch_incremental(cursor=cursor, limit=min(batch_size, max_records - processed)) if mode == "incremental" else adapter.fetch(cursor=cursor, limit=min(batch_size, max_records - processed))
                if not page.records:
                    break
                # GitHub/Slack may attach the next-page cursor to every record.
                # Such cursors are committed only after the whole page completes.
                page_cursor_is_page_level = bool(
                    len(page.records) > 1 and page.next_cursor is not None
                    and all(r.cursor == page.next_cursor for r in page.records)
                )
                report.fetched += len(page.records)
                for record in page.records:
                    source_record_id = self.provenance.source_record_id(config.id, record, tenant_id=self.client.settings.tenant_id)
                    if dry_run:
                        normalized = normalizer.normalize(source_record_id, record)
                        report.normalized += 1
                        proposed, resolved_count, quarantined_count = self._dry_run_record(config, record, source_record_id, normalized)
                        report.proposed_mutations.extend(proposed)
                        report.resolved += resolved_count
                        report.quarantined += 1 if quarantined_count or (not normalized.entities and normalized.warnings) else 0
                        report.warnings.extend(normalized.warnings)
                        if not page_cursor_is_page_level:
                            cursor = record.cursor or cursor
                        processed += 1
                        continue

                    source_record_id, existed = self.provenance.persist_source_record(config, run_id, record)
                    # Re-reading the exact same immutable SourceRecord during a full resync
                    # is not a source update and must not append a second audit event.
                    # A genuine new version is identified by the SUPERSEDES edge created
                    # by persist_source_record().
                    if not existed:
                        persisted = GraphSnapshot.load(self.client)
                        is_update = bool(persisted.edges_from(source_record_id, {"SUPERSEDES"}))
                        event_type = "SOURCE_RECORD_UPDATED" if is_update else "SOURCE_RECORD_INGESTED"
                        self.events.record(event_type, about_ids=[source_record_id, run_id], summary=f"{event_type}: {record.record_type} {record.external_id}", event_id=stable_id("EVT-P9-", event_type, source_record_id), occurred_at=record.fetched_at, properties={"phase": "9", "source_id": source_id})

                    if record.deleted:
                        previous_graph = GraphSnapshot.load(self.client)
                        tombstone = self.writer.write_tombstone(config=config, run_id=run_id,
                                                               source_record_id=source_record_id, record=record)
                        delta = graph_delta(previous_graph, GraphSnapshot.load(self.client),
                                            [source_record_id, tombstone['tombstone_evidence_id'],
                                             *tombstone['affected_entities']])
                        if delta:
                            # Source deletion has been observed, but the writer deliberately
                            # keeps canonical facts. Do not pretend canonical deletion verified.
                            self.reactive.publish(source_record_id=source_record_id,
                                source_checksum=record.checksum, changes=delta,
                                authority='TOMBSTONE_UNRESOLVED', ingestion_run_id=run_id,
                                source_id=config.id)
                            self.reactive.process(limit=8)
                        if self.retrieval_indexer is not None:
                            self.retrieval_indexer.index_source_record(source_record_id)
                        report.written += 1
                        report.updated += 1 if existed else 0
                        if not page_cursor_is_page_level:
                            cursor = record.cursor or cursor
                        self._advance_cursor(source_id, cursor)
                        processed += 1
                        continue

                    normalized = normalizer.normalize(source_record_id, record)
                    report.normalized += 1
                    report.warnings.extend(normalized.warnings)
                    if not normalized.entities:
                        self._quarantine_unmapped(source_record_id, source_id, normalized.warnings[0] if normalized.warnings else "NO_NORMALIZED_ENTITY")
                        report.quarantined += 1
                        if not page_cursor_is_page_level:
                            cursor = record.cursor or cursor
                        self._advance_cursor(source_id, cursor)
                        processed += 1
                        continue

                    artifact_metas = []
                    for artifact_payload in normalized.artifacts:
                        if not self.artifacts.should_externalize(artifact_payload):
                            continue
                        meta = self.artifacts.put(artifact_payload, tenant_id=self.client.settings.tenant_id, source_type=config.source_type, source_record_id=source_record_id)
                        artifact_metas.append(meta)
                        self.provenance.link_artifact(source_record_id, meta, source_id=config.id)
                        report.artifacts += 1
                        self.events.record("ARTIFACT_STORED", about_ids=[meta.artifact_id, source_record_id], summary=f"Stored artifact {meta.artifact_id}", event_id=stable_id("EVT-P9-", "ARTIFACT_STORED", meta.artifact_id), properties={"phase": "9", "source_id": source_id})

                    decisions = []
                    unresolved = False
                    external_identities: dict[str, str] = {}
                    for entity in normalized.entities:
                        decision = self.resolution.resolve(source_record_id, entity, config)
                        decisions.append(decision)
                        if decision.canonical_id:
                            report.resolved += 1
                            ext_identity_id = None
                            if entity.requires_resolution:
                                identity = {**entity.identity}
                                identity.setdefault("external_id", entity.identity.get("username") or entity.identity.get("email") or f"{record.external_id}:{entity.key}")
                                ext_identity_id = self.provenance.external_identity(config, source_record_id, entity_key=entity.key, identity=identity)
                                external_identities[entity.key] = ext_identity_id
                            self.provenance.link_resolution(source_record_id=source_record_id, external_identity_id=ext_identity_id, canonical_id=decision.canonical_id, confidence=decision.confidence, source_id=config.id, mapping_rule=normalized.mapping_rule)
                            self.events.record("ENTITY_RESOLVED", about_ids=[source_record_id, decision.canonical_id], summary=f"Resolved {entity.key} to {decision.canonical_id}", event_id=stable_id("EVT-P9-", "ENTITY_RESOLVED", source_record_id, entity.key, decision.canonical_id), properties={"phase": "9", "resolution_status": decision.status.value})
                        else:
                            unresolved = True
                    if unresolved:
                        report.quarantined += 1
                        self.events.record("ENTITY_RESOLUTION_QUARANTINED", about_ids=[source_record_id], summary=f"Ambiguous identity in {source_record_id}", event_id=stable_id("EVT-P9-", "ENTITY_RESOLUTION_QUARANTINED", source_record_id), properties={"phase": "9"})

                    before_write = GraphSnapshot.load(self.client)
                    write_result = self.writer.write(config=config, run_id=run_id, source_record_id=source_record_id, record=record, normalized=normalized, resolutions=decisions, artifacts=artifact_metas)
                    report.warnings.extend(write_result.get("warnings") or [])
                    if self.retrieval_indexer is not None:
                        self.retrieval_indexer.index_source_record(source_record_id)
                        for meta in artifact_metas:
                            # A parsed SQL dump is represented by canonical table,
                            # column and constraint facts. Chunking its COPY rows as
                            # retrieval prose can leave a manual sync running for
                            # minutes after those facts have already been written.
                            if record.record_type != "sql_file":
                                self.retrieval_indexer.index_artifact(meta.artifact_id)

                    if write_result.get("written_nodes") or write_result.get("written_relationships"):
                        report.written += 1
                        if existed:
                            report.updated += 1
                        self.events.record("EXTERNAL_FACT_WRITTEN", about_ids=[source_record_id] + list(write_result.get("entity_map", {}).values()), summary=f"Wrote normalized facts from {source_record_id}", event_id=stable_id("EVT-P9-", "EXTERNAL_FACT_WRITTEN", source_record_id, record.checksum), properties={"phase": "9", "mapping_rule": normalized.mapping_rule})
                        # Compare committed graph facts, not fetched claims. A duplicate source
                        # record with no factual delta must not trigger learning again.
                        changed_ids = [source_record_id, *write_result.get('entity_map', {}).values()]
                        changes = graph_delta(before_write, GraphSnapshot.load(self.client), changed_ids)
                        if changes:
                            self.reactive.publish(source_record_id=source_record_id,
                                source_checksum=record.checksum, changes=changes,
                                authority=config.trust_class.value, ingestion_run_id=run_id,
                                source_id=config.id)
                            # Eager bounded application; the durable inbox also allows replay.
                            self.reactive.process(limit=8)

                    if not page_cursor_is_page_level:
                        cursor = record.cursor or cursor
                    self._advance_cursor(source_id, cursor)
                    processed += 1
                    if fail_after_committed is not None and processed >= fail_after_committed:
                        raise RuntimeError("Simulated ingestion crash after committed records")
                if page_cursor_is_page_level:
                    # A mid-page crash must replay only the unfinished page,
                    # never skip its remaining records.
                    cursor = page.next_cursor
                    if not dry_run:
                        self._advance_cursor(source_id, cursor)
                if not page.has_more or processed >= max_records:
                    break
                cursor = page.next_cursor or cursor

            report.cursor_end = cursor
            if dry_run:
                report.status = IngestionRunStatus.DRY_RUN
                return report
            report.status = IngestionRunStatus.SUCCEEDED
            self.provenance.complete_run(run_id, status="SUCCEEDED", cursor_end=cursor, counters={
                "records_fetched": report.fetched, "records_normalized": report.normalized, "records_written": report.written,
                "records_quarantined": report.quarantined, "records_failed": report.failed, "artifacts_stored": report.artifacts,
            })
            self.events.record("INGESTION_RUN_COMPLETED", about_ids=[run_id, source_id], summary=f"Completed ingestion from {source_id}", event_id=stable_id("EVT-P9-", "INGESTION_RUN_COMPLETED", run_id), properties={"phase": "9", "written": report.written, "quarantined": report.quarantined})
            return report
        except Exception as exc:
            report.failed += 1
            report.cursor_end = cursor
            report.warnings.append(f"INGESTION_ERROR:{type(exc).__name__}:{exc}")
            if dry_run:
                report.status = IngestionRunStatus.FAILED
                return report
            report.status = IngestionRunStatus.PARTIAL if processed else IngestionRunStatus.FAILED
            self.provenance.complete_run(run_id, status=report.status.value, cursor_end=cursor, counters={
                "records_fetched": report.fetched, "records_normalized": report.normalized, "records_written": report.written,
                "records_quarantined": report.quarantined, "records_failed": report.failed, "artifacts_stored": report.artifacts,
            })
            self.events.record("INGESTION_RUN_FAILED", about_ids=[run_id, source_id], summary=f"Ingestion failed for {source_id}: {exc}", event_id=stable_id("EVT-P9-", "INGESTION_RUN_FAILED", run_id), properties={"phase": "9", "error": str(exc)})
            return report

    @staticmethod
    def _public_run(snapshot: GraphSnapshot, node: dict[str, Any]) -> dict[str, Any]:
        result = dict(node)
        if not result.get("source_id"):
            source_id = result.get("source_ref_id")
            if not source_id:
                edge = next(iter(snapshot.edges_from(str(result.get("id")), {"DERIVED_FROM"})), None)
                source_id = edge.target if edge else None
            if source_id:
                result["source_id"] = source_id
        return result

    def list_runs(self) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        runs = [self._public_run(snapshot, n) for n in snapshot.nodes.values() if has_label(n, "IngestionRun")]
        return sorted(runs, key=lambda x: str(x.get("started_at") or ""), reverse=True)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        node = snapshot.node(run_id)
        return self._public_run(snapshot, node) if has_label(node, "IngestionRun") else None

    def get_artifact_metadata(self, artifact_id: str) -> dict[str, Any] | None:
        node = GraphSnapshot.load(self.client).node(artifact_id)
        return node if has_label(node, "Artifact") else None
