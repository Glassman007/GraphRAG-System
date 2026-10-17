# Human Presentation Model

Phase 13 inserts a deterministic presentation layer between canonical API objects and UI components. The backend ontology is unchanged.

Presentation adapters include `PresentedEntity`, `PresentedRelationship`, `PresentedClaim`, `PresentedEvidence`, `PresentedRisk`, `PresentedSource`, `PresentedIngestionRun`, confidence/status/temporal presenters and retrieval presentation.

Global priority: human name → organizational type/context → meaning/status → canonical ID. Raw dictionaries are not the default UI. `TechnicalDetails` preserves inspectability through progressive disclosure. No LLM is authoritative for presentation.
