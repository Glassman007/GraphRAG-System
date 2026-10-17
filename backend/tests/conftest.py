from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from scripts.seed_lib import seed_all


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def integration_client():
    graph_name = f"company_brain_test_{uuid.uuid4().hex[:8]}"
    settings = Settings(
        falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
        falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
        falkordb_graph=graph_name,
        falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
        tenant_id="northstar",
    )
    try:
        client = FalkorGraphClient(settings)
        client.health_check()
    except Exception as exc:
        pytest.skip(f"FalkorDB integration instance is unavailable at {settings.falkordb_host}:{settings.falkordb_port}: {exc}")
    client.delete_graph()
    seed_all(client)
    yield client
    client.delete_graph()
