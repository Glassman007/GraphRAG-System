"""Tenant-authorized read-only catalogue: sources belong to registered Company Brains.

Never infer a Company Brain from a DataSource ID or return arbitrary FalkorDB graphs.
Fixture/seed sources are visible but are NOT operational ingestion configurations.
"""
from __future__ import annotations

from typing import Any

from backend.app.graph.mutations import upsert_node
from backend.app.services.phase6_utils import now_iso
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.ingestion.source_control import SourceControlService

from backend.app.graph.registry import GraphRegistry
from backend.app.services.phase4_graph import GraphSnapshot, has_label


def list_source_catalog(*, tenant_id: str, registry: GraphRegistry | None = None) -> dict[str, Any]:
    registry = registry or GraphRegistry()
    brain_list = registry.list_for_tenant(tenant_id=tenant_id)
    items: list[dict[str, Any]] = []
    for brain in brain_list['items']:
        if not brain.get('available'):
            continue
        graph_id = brain['graph_id']
        client = registry.client_for_graph(tenant_id=tenant_id, graph_id=graph_id)
        snapshot = GraphSnapshot.load(client)
        for node in snapshot.nodes.values():
            if not has_label(node, 'DataSource') or node.get('configuration_removed') or node.get('catalog_hidden'):
                continue
            source_id = str(node.get('id') or '')
            if not source_id:
                continue
            managed = node.get('managed_by') == 'phase13-source-control'
            # Seeded DataSource records are historical provenance, not live connections.
            items.append({
                'source_id': source_id,
                'display_name': str(node.get('display_name') or node.get('name') or source_id),
                'graph_id': graph_id,
                'brain_name': brain['display_name'],
                'connector_type': str(node.get('connector_type') or node.get('source_type') or 'historical'),
                'connection_mode': str(node.get('connection_mode') or ('fixture' if node.get('fixture_pack') else 'historical')),
                'managed': managed,
                'can_sync': managed and bool(node.get('enabled', True)),
                'status': str(node.get('last_ingestion_status') or node.get('lifecycle_status') or ('IMPORTED' if not managed else 'DRAFT')),
                'fixture_pack': str(node.get('fixture_pack') or '') or None,
            })
    items.sort(key=lambda item: (item['brain_name'].casefold(), item['display_name'].casefold(), item['source_id']))
    return {'items': items, 'brains': brain_list['items']}


def remove_source_from_catalog(*, tenant_id: str, graph_id: str, source_id: str,
                               actor_id: str, registry: GraphRegistry | None = None) -> dict[str, Any]:
    """Hide a source from selection without silently deleting organizational evidence.

    The graph must be explicitly selected and authorized. Managed connectors use
    the existing configuration-removal implementation (including credential removal).
    Seeded/imported sources are only hidden from the catalog; their historical
    DataSource and evidence nodes remain queryable for audit/provenance purposes.
    """
    if not graph_id or not source_id:
        raise ValueError('Explicit Company Brain and source ID are required')
    registry = registry or GraphRegistry()
    client = registry.client_for_graph(tenant_id=tenant_id, graph_id=graph_id)
    snapshot = GraphSnapshot.load(client)
    node = snapshot.node(source_id)
    if (not node or not has_label(node, 'DataSource') or
            node.get('tenant_id') != tenant_id or
            node.get('configuration_removed') or node.get('catalog_hidden')):
        raise KeyError(source_id)
    if node.get('managed_by') == 'phase13-source-control':
        result = SourceControlService(client).delete_configuration(source_id, actor_id=actor_id)
        return {**result, 'graph_id': graph_id, 'action': 'CONFIGURATION_REMOVED'}
    # Read-only fixture provenance is retained; only catalog visibility changes.
    upsert_node(client, 'DataSource', source_id, {
        'catalog_hidden': True, 'catalog_hidden_at': now_iso(),
        'catalog_hidden_by': actor_id,
    })
    EventLedgerService(client).record(
        'SOURCE_CATALOG_HIDDEN', about_ids=[source_id], actor_id=actor_id,
        summary=f'Catalog visibility removed for source {source_id}; provenance retained',
    )
    return {
        'source_id': source_id, 'graph_id': graph_id,
        'catalog_hidden': True, 'historical_provenance_retained': True,
        'action': 'CATALOG_HIDDEN',
    }


def inspect_source_removal(*, tenant_id: str, graph_id: str, source_id: str,
                           registry: GraphRegistry | None = None) -> dict[str, Any]:
    """Read-only source footprint in a shared graph. Never authorizes a purge.

    `NORMALIZED_TO` shows which canonical nodes source records produced, but
    canonical nodes can also be used by other sources or manually authored.
    This audit is intentionally conservative: it never claims deletability.
    """
    if not graph_id or not source_id:
        raise ValueError('Explicit Company Brain and source ID are required')
    registry = registry or GraphRegistry()
    client = registry.client_for_graph(tenant_id=tenant_id, graph_id=graph_id)
    snap = GraphSnapshot.load(client)
    node = snap.node(source_id)
    if not has_label(node, 'DataSource') or node.get('tenant_id') != tenant_id:
        raise KeyError(source_id)
    sources = [n for n in snap.nodes.values() if has_label(n, 'DataSource')]
    records = [n for n in snap.nodes.values() if has_label(n, 'SourceRecord')
               and (n.get('source_id') == source_id or n.get('source_ref_id') == source_id)]
    record_ids = {str(n['id']) for n in records}
    canonical_ids = {e.target for rid in record_ids for e in snap.edges_from(rid, {'NORMALIZED_TO'})}
    other_records = {str(n['id']) for n in snap.nodes.values() if has_label(n, 'SourceRecord')
                     and str(n['id']) not in record_ids}
    other_canonical = {e.target for rid in other_records for e in snap.edges_from(rid, {'NORMALIZED_TO'})}
    shared = canonical_ids & other_canonical
    direct_nodes = [n for n in snap.nodes.values() if n.get('source_ref_id') == source_id
                    or n.get('source_id') == source_id]
    tagged_edges = [e for e in snap.edges if e.properties.get('source_ref_id') == source_id]
    return {
        'graph_id': graph_id, 'tenant_id': tenant_id, 'source_id': source_id,
        'display_name': node.get('display_name') or node.get('name') or source_id,
        'managed': node.get('managed_by') == 'phase13-source-control',
        'source_records': len(record_ids),
        'canonical_entities_reached': len(canonical_ids),
        'canonical_entities_also_referenced_by_other_source_records': len(shared),
        'direct_source_tagged_nodes': len(direct_nodes),
        'source_tagged_edges': len(tagged_edges),
        'data_sources_in_selected_graph': len(sources),
        'graph_shared_by_multiple_sources': len(sources) > 1,
        'supported_removal': 'DISCONNECT_AND_RETAIN_PROVENANCE',
        'hard_purge_safe': False,
        'warning': 'This is a lineage inventory, not a proof that unshared nodes are safe to delete. '
                   'Full removal requires validated exclusive ownership and index/artifact cleanup.',
    }
