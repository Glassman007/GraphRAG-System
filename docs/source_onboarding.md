# Source Onboarding

The Phase 13 wizard follows eight product steps: choose connector → connection details → authentication → scope → mapping → test connection → preview ingestion → connect and sync. Normal users never edit raw source JSON.

Testing performs adapter health checks without Company Brain writes. Preview executes the real Phase 9 pipeline in dry-run mode and reports fetched/normalized/candidate entity/candidate relationship/ambiguous/error/planned-write counts while asserting no canonical graph mutation.

After sync, Source Detail shows health, freshness, runs, records, errors, identity review, lineage and a human summary of systems/teams/people/projects/policies learned from that source.
