from pathlib import Path

import pytest

from backend.app.ingestion.credentials import LocalCredentialStore
from backend.app.ingestion.models import SourceConfig
from backend.app.ingestion.source_control import CONNECTORS, MAPPING_EXAMPLES, SourceControlService


def test_phase13_connector_catalog_contains_phase9_adapters():
    assert set(CONNECTORS) == {"github","jira","slack","teams","database","internal_api","documents","telemetry"}

@pytest.mark.parametrize("name", sorted(CONNECTORS))
def test_phase13_connector_metadata_is_product_facing(name):
    c=CONNECTORS[name]
    assert c.display_name and c.description and c.category
    assert isinstance(c.supported_auth_methods, tuple)
    assert c.supports_test_connection is True
    assert c.supports_preview is True


def test_phase13_mapping_examples_are_deterministic():
    for connector in CONNECTORS:
        assert connector in MAPPING_EXAMPLES
        assert all({"external","canonical","meaning"} <= set(item) for item in MAPPING_EXAMPLES[connector])


def test_phase13_local_credential_store_keeps_values_server_side(tmp_path: Path):
    store=LocalCredentialStore(tmp_path)
    ref=store.put("northstar","SRC-1",{"token":"top-secret","username":"bot"})
    assert ref == "secret://local/northstar/SRC-1"
    assert store.exists(ref)
    assert store.metadata(ref) == {"configured":True,"provider":"local-protected","fields":["token","username"]}
    assert store.resolve_for_connector(ref)["token"] == "top-secret"


def test_phase13_local_credential_store_delete(tmp_path: Path):
    store=LocalCredentialStore(tmp_path);ref=store.put("northstar","SRC-1",{"token":"x"});store.delete(ref)
    assert not store.exists(ref)


def test_phase13_source_config_public_dict_redacts_secret_named_settings():
    cfg=SourceConfig(id="x",source_type="github",name="x",source_instance="x",settings={"token":"bad","token_env":"GITHUB_TOKEN","org":"northstar"},credential_ref="secret://local/northstar/x")
    public=cfg.public_dict()
    assert public["settings"]["token"] == "<redacted-config-reference>"
    assert public["settings"]["token_env"] == "<redacted-config-reference>"
    assert "bad" not in str(public)


def test_phase13_source_config_can_reference_secret_without_storing_value():
    cfg=SourceConfig(id="x",source_type="github",name="x",source_instance="x",credential_ref="secret://local/northstar/x")
    assert cfg.credential_ref.startswith("secret://")
    assert "token" not in cfg.model_dump()


def test_phase13_unsupported_connector_rejected_without_graph():
    service=object.__new__(SourceControlService)
    with pytest.raises(ValueError,match="Unsupported connector"):
        SourceControlService.connector(service,"arbitrary-script")

def test_phase13_live_database_rejects_user_sql(monkeypatch):
    service=object.__new__(SourceControlService)
    monkeypatch.setenv("GRAPH_HACKS_REGISTERED_DATABASE_VIEWS_JSON", '{}')
    with pytest.raises(ValueError, match="forbidden fields"):
        SourceControlService._safe_connection_config(service,"database","live",{"settings":{"query":"SELECT * FROM secrets"}})


def test_phase13_live_internal_api_requires_server_registered_endpoint(monkeypatch):
    service=object.__new__(SourceControlService)
    monkeypatch.setenv("GRAPH_HACKS_REGISTERED_INTERNAL_APIS_JSON", '{}')
    with pytest.raises(ValueError, match="server-registered endpoint"):
        SourceControlService._safe_connection_config(service,"internal_api","live",{"registered_endpoint":"user-url"})


def test_phase13_live_connector_url_must_be_https_and_allowlisted(monkeypatch):
    service=object.__new__(SourceControlService)
    monkeypatch.setenv("GRAPH_HACKS_ALLOWED_CONNECTOR_HOSTS", "api.github.com,slack.com")
    with pytest.raises(ValueError, match="allowlist"):
        SourceControlService._safe_connection_config(service,"github","live",{"base_url":"https://attacker.example"})
