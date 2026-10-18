from __future__ import annotations

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us

_REL_ACTIVE = "(r._ts_valid_from_us IS NULL OR r._ts_valid_from_us <= $as_of_us) AND (r._ts_valid_until_us IS NULL OR r._ts_valid_until_us > $as_of_us)"
_REL_ACTIVE_O = "(o._ts_valid_from_us IS NULL OR o._ts_valid_from_us <= $as_of_us) AND (o._ts_valid_until_us IS NULL OR o._ts_valid_until_us > $as_of_us)"
_REL_ACTIVE_M = "(m._ts_valid_from_us IS NULL OR m._ts_valid_from_us <= $as_of_us) AND (m._ts_valid_until_us IS NULL OR m._ts_valid_until_us > $as_of_us)"


def claims_about(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id})-[a:ABOUT]->(s:Entity {tenant_id:$tenant_id, id:$subject_id})
        RETURN c, a.valid_from AS about_valid_from
        ORDER BY c._ts_created_at_us, c.id
        """,
        {"tenant_id": client.settings.tenant_id, "subject_id": subject_id},
    )


def claim_core(client: FalkorGraphClient, claim_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})
        OPTIONAL MATCH (c)-[:ABOUT]->(s:Entity {tenant_id:$tenant_id})
        OPTIONAL MATCH (c)-[:ASSERTED_BY]->(actor:Entity {tenant_id:$tenant_id})
        RETURN c, s, actor
        ORDER BY s.id, actor.id
        """,
        {"tenant_id": client.settings.tenant_id, "claim_id": claim_id},
    )


def claim_evidence(client: FalkorGraphClient, claim_id: str):
    return client.read(
        """
        MATCH (e:Entity:Evidence {tenant_id:$tenant_id})-[rel:SUPPORTS|REFUTES]->
              (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})
        OPTIONAL MATCH (e)-[:DERIVED_FROM]->(src:Entity {tenant_id:$tenant_id})
        RETURN e, type(rel) AS relation_type, rel.confidence AS relation_confidence,
               rel.valid_from AS relation_valid_from, src
        ORDER BY e._ts_observed_at_us, e.id, src.id
        """,
        {"tenant_id": client.settings.tenant_id, "claim_id": claim_id},
    )


def claim_conflicts(client: FalkorGraphClient, claim_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})-[rel:CONTRADICTS]-
              (other:Entity:Claim {tenant_id:$tenant_id})
        RETURN other, rel.scope AS scope, rel.confidence AS confidence,
               rel.valid_from AS detected_at, rel.source_ref_id AS source_ref_id
        ORDER BY other._ts_created_at_us, other.id
        """,
        {"tenant_id": client.settings.tenant_id, "claim_id": claim_id},
    )


def subject_conflicts(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (a:Entity:Claim {tenant_id:$tenant_id})-[:ABOUT]->
              (s:Entity {tenant_id:$tenant_id, id:$subject_id})
        MATCH (a)-[rel:CONTRADICTS]-(b:Entity:Claim {tenant_id:$tenant_id})
        MATCH (b)-[:ABOUT]->(s)
        RETURN DISTINCT a, b, rel.scope AS scope, rel.confidence AS confidence,
               rel.valid_from AS detected_at, rel.source_ref_id AS source_ref_id
        ORDER BY a.id, b.id
        """,
        {"tenant_id": client.settings.tenant_id, "subject_id": subject_id},
    )


def claim_supersession(client: FalkorGraphClient, claim_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})
        OPTIONAL MATCH (newer:Entity:Claim {tenant_id:$tenant_id})-[incoming:SUPERSEDES]->(c)
        OPTIONAL MATCH (c)-[outgoing:SUPERSEDES]->(older:Entity:Claim {tenant_id:$tenant_id})
        RETURN newer, incoming.valid_from AS superseded_at,
               older, outgoing.valid_from AS supersedes_at
        ORDER BY superseded_at, supersedes_at
        """,
        {"tenant_id": client.settings.tenant_id, "claim_id": claim_id},
    )



def claim_sources(client: FalkorGraphClient, claim_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})-[:DERIVED_FROM]->
              (src:Entity {tenant_id:$tenant_id})
        RETURN src
        ORDER BY src.id
        """,
        {"tenant_id": client.settings.tenant_id, "claim_id": claim_id},
    )

def claim_context_entities(client: FalkorGraphClient, claim_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})-[:ABOUT]->(ctx:Entity {tenant_id:$tenant_id})
        RETURN DISTINCT ctx
        UNION
        MATCH (e:Entity:Evidence {tenant_id:$tenant_id})-[:SUPPORTS|REFUTES]->
              (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})
        MATCH (e)-[:ABOUT]->(ctx:Entity {tenant_id:$tenant_id})
        RETURN DISTINCT ctx
        UNION
        MATCH (e:Entity:Evidence {tenant_id:$tenant_id})-[:SUPPORTS|REFUTES]->
              (c:Entity:Claim {tenant_id:$tenant_id, id:$claim_id})
        MATCH (e)-[:ABOUT]->(ch:Entity:Change {tenant_id:$tenant_id})-[:CHANGED|AFFECTS]->
              (ctx:Entity {tenant_id:$tenant_id})
        RETURN DISTINCT ctx
        """,
        {"tenant_id": client.settings.tenant_id, "claim_id": claim_id},
    )


def actor_responsibility_paths(client: FalkorGraphClient, actor_id: str, context_ids: list[str], as_of: str):
    if not context_ids:
        return client.read("RETURN 1 AS ignored LIMIT 0")
    return client.read(
        f"""
        MATCH (actor:Entity {{tenant_id:$tenant_id, id:$actor_id}})-[r:RESPONSIBLE_FOR]->
              (ctx:Entity {{tenant_id:$tenant_id}})
        WHERE ctx.id IN $context_ids AND {_REL_ACTIVE}
        RETURN actor, r.confidence AS confidence, ctx
        ORDER BY ctx.id
        """,
        {"tenant_id": client.settings.tenant_id, "actor_id": actor_id, "context_ids": context_ids, "as_of_us": to_epoch_us(as_of)},
    )


def actor_owner_paths(client: FalkorGraphClient, actor_id: str, context_ids: list[str], as_of: str):
    if not context_ids:
        return client.read("RETURN 1 AS ignored LIMIT 0")
    return client.read(
        f"""
        MATCH (actor:Entity:Person {{tenant_id:$tenant_id, id:$actor_id}})-[m:MEMBER_OF]->
              (team:Entity:Team {{tenant_id:$tenant_id}})-[o:OWNS]->
              (ctx:Entity {{tenant_id:$tenant_id}})
        WHERE ctx.id IN $context_ids
          AND {_REL_ACTIVE_M}
          AND {_REL_ACTIVE_O}
        RETURN actor, team, o.confidence AS ownership_confidence, o.authoritative AS authoritative, ctx
        ORDER BY ctx.id, team.id
        """,
        {"tenant_id": client.settings.tenant_id, "actor_id": actor_id, "context_ids": context_ids, "as_of_us": to_epoch_us(as_of)},
    )


def actor_expertise_paths(client: FalkorGraphClient, actor_id: str, context_ids: list[str], as_of: str):
    if not context_ids:
        return client.read("RETURN 1 AS ignored LIMIT 0")
    return client.read(
        f"""
        MATCH (actor:Entity:Person {{tenant_id:$tenant_id, id:$actor_id}})-[r:EXPERT_IN]->
              (ctx:Entity {{tenant_id:$tenant_id}})
        WHERE ctx.id IN $context_ids AND {_REL_ACTIVE}
        RETURN actor, r.confidence AS confidence, ctx
        ORDER BY confidence DESC, ctx.id
        """,
        {"tenant_id": client.settings.tenant_id, "actor_id": actor_id, "context_ids": context_ids, "as_of_us": to_epoch_us(as_of)},
    )


def actor_approval_paths(client: FalkorGraphClient, actor_id: str, context_ids: list[str], as_of: str):
    if not context_ids:
        return client.read("RETURN 1 AS ignored LIMIT 0")
    return client.read(
        f"""
        MATCH (approved:Entity {{tenant_id:$tenant_id}})-[r:APPROVED_BY]->
              (actor:Entity {{tenant_id:$tenant_id, id:$actor_id}})
        WHERE approved.id IN $context_ids AND {_REL_ACTIVE}
        RETURN actor, approved, 'DIRECT' AS path_kind
        UNION
        MATCH (deployment:Entity:Deployment {{tenant_id:$tenant_id}})-[r:APPROVED_BY]->
              (actor:Entity {{tenant_id:$tenant_id, id:$actor_id}})
        MATCH (deployment)-[:CONTAINS]->(change:Entity:Change {{tenant_id:$tenant_id}})-[:CHANGED|AFFECTS]->
              (ctx:Entity {{tenant_id:$tenant_id}})
        WHERE ctx.id IN $context_ids AND {_REL_ACTIVE}
        RETURN actor, deployment AS approved, 'DEPLOYMENT_CHANGE_SCOPE' AS path_kind
        """,
        {"tenant_id": client.settings.tenant_id, "actor_id": actor_id, "context_ids": context_ids, "as_of_us": to_epoch_us(as_of)},
    )


def governing_policies(client: FalkorGraphClient, context_ids: list[str], as_of: str):
    if not context_ids:
        return client.read("RETURN 1 AS ignored LIMIT 0")
    return client.read(
        f"""
        MATCH (p:Entity:Policy {{tenant_id:$tenant_id}})-[r:GOVERNS]->
              (ctx:Entity {{tenant_id:$tenant_id}})
        WHERE ctx.id IN $context_ids AND {_REL_ACTIVE}
        RETURN p, r.authoritative AS authoritative, ctx
        ORDER BY p.id, ctx.id
        """,
        {"tenant_id": client.settings.tenant_id, "context_ids": context_ids, "as_of_us": to_epoch_us(as_of)},
    )


def current_owners(client: FalkorGraphClient, entity_id: str, as_of: str):
    return client.read(
        f"""
        MATCH (owner:Entity {{tenant_id:$tenant_id}})-[r:OWNS]->
              (resource:Entity {{tenant_id:$tenant_id, id:$entity_id}})
        WHERE {_REL_ACTIVE}
        RETURN owner, r.valid_from AS valid_from, r.valid_until AS valid_until,
               r.confidence AS confidence, r.authoritative AS authoritative, r.source_ref_id AS source_ref_id
        ORDER BY r._ts_valid_from_us DESC, owner.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id, "as_of_us": to_epoch_us(as_of)},
    )


def ownership_history(client: FalkorGraphClient, entity_id: str):
    return client.read(
        """
        MATCH (owner:Entity {tenant_id:$tenant_id})-[r:OWNS]->
              (resource:Entity {tenant_id:$tenant_id, id:$entity_id})
        RETURN owner, r.valid_from AS valid_from, r.valid_until AS valid_until,
               r.confidence AS confidence, r.authoritative AS authoritative, r.source_ref_id AS source_ref_id
        ORDER BY r._ts_valid_from_us DESC, owner.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id},
    )


def current_responsibility(client: FalkorGraphClient, entity_id: str, as_of: str):
    return client.read(
        f"""
        MATCH (actor:Entity {{tenant_id:$tenant_id}})-[r:RESPONSIBLE_FOR]->
              (resource:Entity {{tenant_id:$tenant_id, id:$entity_id}})
        WHERE {_REL_ACTIVE}
        RETURN actor, r.confidence AS confidence, r.valid_from AS valid_from,
               r.valid_until AS valid_until, r.source_ref_id AS source_ref_id
        ORDER BY confidence DESC, actor.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id, "as_of_us": to_epoch_us(as_of)},
    )


def expertise_history(client: FalkorGraphClient, entity_id: str):
    return client.read(
        """
        MATCH (person:Entity:Person {tenant_id:$tenant_id})-[r:EXPERT_IN]->
              (resource:Entity {tenant_id:$tenant_id, id:$entity_id})
        RETURN person, r.confidence AS confidence, r.valid_from AS valid_from,
               r.valid_until AS valid_until, r.source_ref_id AS source_ref_id
        ORDER BY confidence DESC, person.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id},
    )


def owner_team_members(client: FalkorGraphClient, entity_id: str, as_of: str):
    return client.read(
        f"""
        MATCH (person:Entity:Person {{tenant_id:$tenant_id}})-[m:MEMBER_OF]->
              (team:Entity:Team {{tenant_id:$tenant_id}})-[o:OWNS]->
              (resource:Entity {{tenant_id:$tenant_id, id:$entity_id}})
        WHERE {_REL_ACTIVE_M} AND {_REL_ACTIVE_O}
        RETURN person, team, m.confidence AS membership_confidence,
               o.confidence AS ownership_confidence, o.authoritative AS authoritative
        ORDER BY team.id, person.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id, "as_of_us": to_epoch_us(as_of)},
    )


def related_approvers(client: FalkorGraphClient, entity_id: str, as_of: str):
    return client.read(
        f"""
        MATCH (deployment:Entity:Deployment {{tenant_id:$tenant_id}})-[approval:APPROVED_BY]->
              (actor:Entity {{tenant_id:$tenant_id}})
        MATCH (deployment)-[:CONTAINS]->(change:Entity:Change {{tenant_id:$tenant_id}})-[:CHANGED|AFFECTS]->
              (resource:Entity {{tenant_id:$tenant_id, id:$entity_id}})
        WHERE {_REL_ACTIVE.replace('r.', 'approval.')}
        RETURN actor, deployment, change, approval.confidence AS confidence
        ORDER BY deployment._ts_created_at_us DESC, actor.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id, "as_of_us": to_epoch_us(as_of)},
    )


def historical_experience(client: FalkorGraphClient, entity_id: str):
    return client.read(
        """
        MATCH (person:Entity:Person {tenant_id:$tenant_id})-[:PRODUCED]->
              (change:Entity:Change {tenant_id:$tenant_id})-[:CHANGED|AFFECTS]->
              (resource:Entity {tenant_id:$tenant_id, id:$entity_id})
        RETURN DISTINCT person, change, 'PRODUCED_CHANGE' AS path_kind
        UNION
        MATCH (deployment:Entity:Deployment {tenant_id:$tenant_id})-[:APPROVED_BY]->
              (person:Entity:Person {tenant_id:$tenant_id})
        MATCH (deployment)-[:CONTAINS]->(change:Entity:Change {tenant_id:$tenant_id})-[:CHANGED|AFFECTS]->
              (resource:Entity {tenant_id:$tenant_id, id:$entity_id})
        RETURN DISTINCT person, change, 'APPROVED_CHANGE' AS path_kind
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id},
    )


def active_systems(client: FalkorGraphClient):
    return client.read(
        """
        MATCH (s:Entity:System {tenant_id:$tenant_id})
        WHERE s.status = 'ACTIVE'
        RETURN s
        ORDER BY s.id
        """,
        {"tenant_id": client.settings.tenant_id},
    )


def current_dependents(client: FalkorGraphClient, entity_id: str, as_of: str):
    return client.read(
        f"""
        MATCH (dependent:Entity:System {{tenant_id:$tenant_id}})-[r:DEPENDS_ON]->
              (resource:Entity:System {{tenant_id:$tenant_id, id:$entity_id}})
        WHERE {_REL_ACTIVE}
        RETURN dependent, r.criticality AS criticality, r.dependency_kind AS dependency_kind,
               r.confidence AS confidence, r.source_ref_id AS source_ref_id
        ORDER BY dependent.id
        """,
        {"tenant_id": client.settings.tenant_id, "entity_id": entity_id, "as_of_us": to_epoch_us(as_of)},
    )
