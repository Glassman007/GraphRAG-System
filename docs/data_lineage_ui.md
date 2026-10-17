# Data Lineage UI

`DataLineagePanel` answers “How did GraphHacks learn this?” using backend provenance. Supported chains are Source → IngestionRun → SourceRecord → Artifact/normalization → canonical Entity/relationship → Evidence/Claim where available.

The entity lineage endpoint is `/api/v1/lineage/entities/{entity_id}`. Source and run IDs are navigable back into the Sources workspace. Missing graph provenance produces an incomplete lineage rather than fabricated explanation.
