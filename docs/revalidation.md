# Phase 7 Revalidation

A stale/invalid Claim may return to `VALIDATED` only when new active Evidence is explicitly linked with `SUPPORTS`.

`revalidate_claim(claim_id, evidence_id)` checks:

- Claim exists;
- Evidence exists and is not INVALIDATED/RETRACTED/SUPERSEDED/REJECTED;
- the Evidence actually supports the Claim in FalkorDB.

The Claim records `revalidated_at`, while prior invalidation/stale history remains reconstructable from Event nodes. `KNOWLEDGE_REVALIDATED` is append-oriented and does not erase the earlier invalidation event.
