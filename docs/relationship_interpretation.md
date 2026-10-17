# Relationship Interpretation

Canonical relationship enums remain unchanged. A deterministic registry translates them for users, for example: `DEPENDS_ON` → “A depends on B”, `OWNS` → “A owns B”, `SUPPORTS` → “This evidence supports B”, `REFUTES` → “This evidence contradicts B”, `NORMALIZED_TO` → “GraphHacks interpreted A as B”, `BEFORE` → “A happened before B”, and `CAUSE` → “A contributed causally to B”.

Unknown enums use a readable deterministic fallback while Technical Mode exposes the canonical relationship type. This preserves the important distinction between chronology (`BEFORE`) and causation (`CAUSE`).
