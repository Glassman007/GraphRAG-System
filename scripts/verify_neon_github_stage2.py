"""Run from the project root: python -m scripts.verify_neon_github_stage2."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.ingestion.adapters.github_http import GitHubApiError
from backend.app.ingestion.models import SourceConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify anonymous Neon SQL-file retrieval without graph writes or SQL execution")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence path (never includes credentials or SQL contents)")
    args = parser.parse_args()
    config = SourceConfig(id="NEON-STAGE2", source_type="github", name="Neon public repository",
                          source_instance="neon-stage2", settings={
                              "repository": "https://github.com/neondatabase/postgres-sample-dbs",
                              "anonymous": True, "files": ["dvdrental.sql"]})
    adapter = GitHubAdapter(config)
    evidence = {"checked_at": datetime.now(timezone.utc).isoformat(), "authentication": "anonymous"}
    health = adapter.health_check()
    evidence["health"] = health
    if not health["ok"]:
        evidence["result"] = "BLOCKED" if health["status"] in {"RATE_LIMITED", "TIMEOUT", "UNREACHABLE"} else "FAIL"
    else:
        try:
            # Keep discovery and paginated fetch on the commit verified by health.
            config.settings["ref"] = health["commit_sha"]
            discovery = adapter.discover_files()
            first = adapter.fetch(limit=1)
            second = adapter.fetch(cursor=first.records[0].cursor, limit=1)
            record = second.records[0]
            content = record.artifacts[0].content
            assert isinstance(content, bytes) and content
            assert b"PostgreSQL database dump" in content[:2048]
            assert first.records[0].record_type == "repository" and first.has_more
            assert record.record_type == "sql_file" and not second.has_more
            assert record.raw_metadata["path"] == "dvdrental.sql"
            assert record.raw_metadata["commit_sha"] == health["commit_sha"]
            assert record.raw_metadata["sha256"] == hashlib.sha256(content).hexdigest()
            evidence.update({"result": "PASS", "discovered_regular_files": len(discovery["files"]),
                             "sample_sql_files": [f["path"] for f in discovery["files"] if f["path"] in {"dvdrental.sql", "pagila.sql", "chinook.sql"}],
                             "fetched_file": record.raw_metadata, "content_bytes": len(content),
                             "content_sha256": hashlib.sha256(content).hexdigest(), "canonical_source_uri": record.canonical_source_uri,
                             "pages_fetched": 2, "sql_executed": False, "graph_written": False})
        except GitHubApiError as exc:
            evidence.update({"result": "BLOCKED" if exc.code in {"RATE_LIMITED", "TIMEOUT", "UNREACHABLE"} else "FAIL",
                             "error_code": exc.code, "message": str(exc)})
    rendered = json.dumps(evidence, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
