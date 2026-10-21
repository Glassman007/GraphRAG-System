"""Stage 2 GitHub transport, scope, snapshot and pagination contracts; no services required."""
import base64
import hashlib
import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.ingestion.adapters import github as module
from backend.app.ingestion.adapters.github import GitHubAdapter, parse_repository
from backend.app.ingestion.adapters.github_http import GitHubApiError, GitHubHttpClient, _NoRedirect
from backend.app.ingestion.models import SourceConfig
from backend.app.ingestion.source_control import SourceControlService

REPO = "neondatabase/postgres-sample-dbs"
COMMIT = "a" * 40
TREE = "b" * 40
CONTENT = b"-- PostgreSQL database dump\nCREATE TABLE public.example (id integer);\n"
BLOB = hashlib.sha1(f"blob {len(CONTENT)}\0".encode() + CONTENT).hexdigest()


def config(**settings):
    return SourceConfig(id="GH", source_type="github", name="Neon", source_instance="neon",
                        settings={"repository": REPO, "anonymous": True, **settings})


def repo_row(name="postgres-sample-dbs", id=123):
    return {"id": id, "name": name, "full_name": f"neondatabase/{name}",
            "default_branch": "main", "html_url": f"https://github.com/neondatabase/{name}",
            "owner": {"login": "neondatabase"}, "language": "SQL"}


@pytest.fixture
def remote(monkeypatch):
    responses = {
        f"/repos/{REPO}": repo_row(),
        f"/repos/{REPO}/commits/main": {"sha": COMMIT, "commit": {"tree": {"sha": TREE}}},
        f"/repos/{REPO}/commits/{COMMIT}": {"sha": COMMIT, "commit": {"tree": {"sha": TREE}}},
        f"/repos/{REPO}/git/trees/{TREE}": {"truncated": False, "tree": [
            {"path": p, "type": "blob", "mode": "100644", "sha": BLOB, "size": len(CONTENT)}
            for p in ("pagila.sql", "dvdrental.sql", "chinook.sql")]},
        f"/repos/{REPO}/git/blobs/{BLOB}": {"sha": BLOB, "encoding": "base64", "content": base64.b64encode(CONTENT).decode()},
    }
    calls, headers = [], []

    class FakeHTTP:
        def __init__(self, **kwargs):
            headers.append(kwargs["headers"])

        def get_json(self, path, query=None):
            calls.append((path, query))
            value = responses[path]
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(module, "ConfiguredJsonHttpClient", FakeHTTP)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return SimpleNamespace(responses=responses, calls=calls, headers=headers)


@pytest.mark.parametrize("value", [REPO, REPO.upper(), f"https://github.com/{REPO}", f"https://github.com/{REPO}.git/"])
def test_repository_parsing(value):
    assert parse_repository(value) == ("neondatabase", "postgres-sample-dbs")


@pytest.mark.parametrize("value", ["https://example.org/a/b", "http://github.com/a/b", "https://token@github.com/a/b",
                                    "https://github.com/a/b/tree/main", "a/../b", "a/%2e%2e", "a/..", "a", "a/b?token=x"])
def test_repository_rejects_unsafe_or_ambiguous_input(value):
    with pytest.raises(ValueError):
        parse_repository(value)


def test_anonymous_health_makes_real_transport_calls(remote, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "do-not-send")
    health = GitHubAdapter(config()).health_check()
    assert health["ok"] and health["commit_sha"] == COMMIT and health["branch"] == "main"
    assert health["checks"]["authentication"] == "NOT_REQUIRED"
    assert [p for p, _ in remote.calls] == [f"/repos/{REPO}", f"/repos/{REPO}/commits/main"]
    assert all("Authorization" not in h for h in remote.headers)


def test_optional_credentials_preserved(remote, monkeypatch):
    monkeypatch.setattr(module, "credential_values", lambda _: {"token": "synthetic-credential"})
    assert GitHubAdapter(config(anonymous=False)).health_check()["checks"]["authentication"] == "PASS"
    assert remote.headers[0]["Authorization"] == "Bearer synthetic-credential"


def test_public_repository_needs_no_authentication_setting(remote, monkeypatch):
    monkeypatch.setattr(module, "credential_values", lambda _: {})
    cfg = config()
    cfg.settings.pop("anonymous")
    assert GitHubAdapter(cfg).health_check()["ok"]
    assert "Authorization" not in remote.headers[0]


@pytest.mark.parametrize("code,status", [("AUTH_FAILED", 401), ("PERMISSION_ERROR", 403), ("NOT_FOUND", 404),
                                        ("RATE_LIMITED", 429), ("API_ERROR", 500), ("TIMEOUT", None), ("UNREACHABLE", None)])
def test_health_failure_classification(remote, code, status):
    remote.responses[f"/repos/{REPO}"] = GitHubApiError(code, "Safe failure", status=status, retry_after="60")
    health = GitHubAdapter(config()).health_check()
    assert not health["ok"] and health["status"] == code and health["retry_after"] == "60"
    assert health["checks"]["reachability"] == ("PASS" if status else "FAIL")


def test_selected_file_bytes_path_commit_and_integrity(remote):
    adapter = GitHubAdapter(config(files=["dvdrental.sql"]))
    page = adapter.fetch(limit=10)
    assert [r.record_type for r in page.records] == ["repository", "sql_file"]
    record = page.records[1]
    assert record.raw_metadata["path"] == "dvdrental.sql"
    assert record.raw_metadata["commit_sha"] == COMMIT and record.raw_metadata["blob_sha"] == BLOB
    assert record.artifacts[0].content == CONTENT
    assert record.canonical_source_uri == f"https://github.com/{REPO}/blob/{COMMIT}/dvdrental.sql"
    assert not page.has_more
    assert [p for p, _ in remote.calls if "/git/blobs/" in p] == [f"/repos/{REPO}/git/blobs/{BLOB}"]


def test_discover_lists_other_dumps_without_downloading(remote):
    snapshot = GitHubAdapter(config()).discover_files()
    assert [f["path"] for f in snapshot["files"]] == ["chinook.sql", "dvdrental.sql", "pagila.sql"]
    assert snapshot["commit_sha"] == COMMIT
    assert not any("/git/blobs/" in p for p, _ in remote.calls)


def test_restart_pins_commit_and_resumes_after_each_record(remote):
    adapter = GitHubAdapter(config(files=["dvdrental.sql", "chinook.sql"]))
    first = adapter.fetch(limit=1)
    # The branch advances between calls. Resuming must use the original SHA.
    remote.responses[f"/repos/{REPO}/commits/main"]["sha"] = "c" * 40
    resumed = GitHubAdapter(config(files=["chinook.sql", "dvdrental.sql"])).fetch(cursor=first.records[0].cursor, limit=5)
    assert [r.raw_metadata["path"] for r in resumed.records] == ["chinook.sql", "dvdrental.sql"]
    assert all(r.version == COMMIT for r in resumed.records)
    assert not resumed.has_more


def test_restart_preserves_original_default_branch(remote):
    adapter = GitHubAdapter(config(files=["dvdrental.sql"]))
    first = adapter.fetch(limit=1)
    remote.responses[f"/repos/{REPO}"]["default_branch"] = "new-default"
    second = adapter.fetch(cursor=first.next_cursor, limit=1)
    assert second.records[0].raw_metadata["branch"] == "main"
    assert second.records[0].version == COMMIT


def test_full_resync_same_snapshot_is_stable(remote):
    adapter = GitHubAdapter(config(files=["dvdrental.sql"]))
    first, second = adapter.fetch(), adapter.fetch()
    assert [(r.external_id, r.checksum) for r in first.records] == [(r.external_id, r.checksum) for r in second.records]


def test_selected_branch_is_encoded(remote):
    remote.responses[f"/repos/{REPO}/commits/feature%2Fsql"] = remote.responses[f"/repos/{REPO}/commits/main"]
    result = GitHubAdapter(config(branch="feature/sql")).health_check()
    assert result["ok"] and result["branch"] == "feature/sql"
    assert (f"/repos/{REPO}/commits/feature%2Fsql", None) in remote.calls


@pytest.mark.parametrize("path", ["../dvdrental.sql", "/dvdrental.sql", "a//b", "a\\b", "a/./b"])
def test_selected_file_path_validation(remote, path):
    with pytest.raises(ValueError):
        GitHubAdapter(config(files=[path])).fetch()


def test_missing_selected_file_is_explicit(remote):
    with pytest.raises(GitHubApiError) as error:
        GitHubAdapter(config(files=["missing.sql"])).fetch()
    assert error.value.code == "NOT_FOUND"


def test_truncated_tree_is_not_reported_complete(remote):
    remote.responses[f"/repos/{REPO}/git/trees/{TREE}"]["truncated"] = True
    with pytest.raises(GitHubApiError) as error:
        GitHubAdapter(config(files=["dvdrental.sql"])).fetch()
    assert error.value.code == "TREE_TRUNCATED"


def test_size_limit_prevents_blob_download(remote):
    with pytest.raises(GitHubApiError) as error:
        GitHubAdapter(config(files=["dvdrental.sql"], max_file_bytes=1)).fetch()
    assert error.value.code == "FILE_TOO_LARGE"
    assert not any("/git/blobs/" in p for p, _ in remote.calls)


def test_corrupt_blob_is_rejected(remote):
    remote.responses[f"/repos/{REPO}/git/blobs/{BLOB}"]["content"] = base64.b64encode(b"corrupt").decode()
    with pytest.raises(GitHubApiError) as error:
        GitHubAdapter(config(files=["dvdrental.sql"])).fetch()
    assert error.value.code == "INVALID_RESPONSE"


def test_changed_scope_rejects_cursor(remote):
    cursor = GitHubAdapter(config(files=["dvdrental.sql"])).fetch(limit=1).next_cursor
    with pytest.raises(ValueError, match="cursor"):
        GitHubAdapter(config(files=["chinook.sql"])).fetch(cursor=cursor)


def org_adapter(monkeypatch, pages, selected=None):
    calls = []

    class OrgHTTP:
        def __init__(self, **kwargs):
            pass

        def get_json(self, path, query=None):
            calls.append(query)
            return pages.get(query["page"], [])

    monkeypatch.setattr(module, "ConfiguredJsonHttpClient", OrgHTTP)
    cfg = SourceConfig(id="org", source_type="github", name="Org", source_instance="org",
                       settings={"org": "neondatabase", "anonymous": True}, scope_config={"selected": selected or []})
    return GitHubAdapter(cfg), calls


def test_filtered_full_pages_do_not_stop_discovery(monkeypatch):
    pages = {1: [repo_row(f"a-{i}", i) for i in range(100)], 2: [repo_row()]}
    adapter, calls = org_adapter(monkeypatch, pages, [REPO.upper()])
    page = adapter.fetch(limit=1)
    assert [r.raw_metadata["full_name"] for r in page.records] == [REPO]
    assert [q["page"] for q in calls] == [1, 2]
    assert all(q["per_page"] == 100 for q in calls)
    assert not page.has_more  # Already reached the short final upstream page.


def test_org_partial_page_record_cursor_and_changed_batch_size(monkeypatch):
    adapter, calls = org_adapter(monkeypatch, {1: [repo_row(f"a-{i}", i + 1) for i in range(100)]})
    first = adapter.fetch(limit=3)
    # Simulate a crash after committing just the first record of that page.
    resumed = adapter.fetch(cursor=first.records[0].cursor, limit=2)
    assert [r.external_id for r in resumed.records] == ["2", "3"]
    assert all(q["per_page"] == 100 for q in calls)


@pytest.mark.parametrize("status,headers,body,code", [
    (401, {}, b"secret-remote-body", "AUTH_FAILED"), (403, {}, b"denied", "PERMISSION_ERROR"),
    (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123"}, b"rate limit", "RATE_LIMITED"),
    (403, {"Retry-After": "60"}, b"secondary rate limit", "RATE_LIMITED"),
    (429, {"Retry-After": "60"}, b"slow down", "RATE_LIMITED"),
    (404, {}, b"missing", "NOT_FOUND"), (500, {}, b"internal", "API_ERROR"), (302, {"Location": "https://other.test"}, b"", "API_ERROR"),
])
def test_transport_errors_are_sanitized(status, headers, body, code):
    client = GitHubHttpClient(base_url="https://api.github.com")
    client._opener = Mock()
    client._opener.open.side_effect = urllib.error.HTTPError("https://api.github.com", status, "error", headers, io.BytesIO(body))
    with pytest.raises(GitHubApiError) as error:
        client.get_json("/repos/a/b")
    assert error.value.code == code and error.value.status == status
    assert "secret-remote-body" not in str(error.value)
    assert error.value.retry_after == headers.get("Retry-After")


@pytest.mark.parametrize("error,code", [(TimeoutError(), "TIMEOUT"), (urllib.error.URLError(TimeoutError()), "TIMEOUT"), (urllib.error.URLError("sensitive-host"), "UNREACHABLE")])
def test_transport_network_failures(error, code):
    client = GitHubHttpClient(base_url="https://api.github.com")
    client._opener = Mock()
    client._opener.open.side_effect = error
    with pytest.raises(GitHubApiError) as caught:
        client.get_json("/repos/a/b")
    assert caught.value.code == code
    assert "sensitive-host" not in str(caught.value)


@pytest.mark.parametrize("payload,limit,code", [(b"not-json", 100, "INVALID_RESPONSE"), (b"12345", 4, "RESPONSE_TOO_LARGE")])
def test_transport_rejects_bad_or_oversized_response(payload, limit, code):
    client = GitHubHttpClient(base_url="https://api.github.com", max_response_bytes=limit)
    client._opener = Mock()
    client._opener.open.return_value.__enter__ = Mock(return_value=io.BytesIO(payload))
    client._opener.open.return_value.__exit__ = Mock(return_value=False)
    with pytest.raises(GitHubApiError) as error:
        client.get_json("/repos/a/b")
    assert error.value.code == code


@pytest.mark.parametrize("url", ["http://api.github.com", "https://evil.test", "https://secret@api.github.com", "https://api.github.com?token=secret"])
def test_transport_rejects_unsafe_base_url(url):
    with pytest.raises(ValueError):
        GitHubHttpClient(base_url=url)


def test_redirects_do_not_forward_credentials():
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test") is None


def test_source_control_accepts_explicit_repository_url():
    service = object.__new__(SourceControlService)
    cfg = service._safe_connection_config("github", "live", {"repository_url": f"https://github.com/{REPO}", "files": ["dvdrental.sql"]})
    assert cfg["settings"]["repository"] == REPO and cfg["settings"]["files"] == ["dvdrental.sql"]
    assert cfg["base_url"] == "https://api.github.com"


@pytest.mark.parametrize("status", ["HEALTHY", "RATE_LIMITED", "AUTH_FAILED", "NOT_FOUND"])
def test_source_control_preserves_adapter_health_details(monkeypatch, status):
    from backend.app.ingestion import source_control as sc
    adapter = Mock()
    adapter.health_check.return_value = {"ok": status == "HEALTHY", "live": True, "status": status,
                                        "checks": {"authentication": "NOT_REQUIRED", "api_access": "PASS" if status == "HEALTHY" else "FAIL"},
                                        "retry_after": "60", "commit_sha": COMMIT}
    service = object.__new__(SourceControlService)
    service.client, service.events, service.credentials = Mock(), Mock(), Mock()
    service._source_node = Mock(return_value={})
    service._registry = Mock(return_value=SimpleNamespace(get=lambda _: (config(), adapter)))
    monkeypatch.setattr(sc, "upsert_node", Mock())
    result = service.test_connection("GH", actor_id="test")
    assert result["status"] == status
    assert result["checks"]["authentication"] == "NOT_REQUIRED"
    assert result["connection_details"]["retry_after"] == "60"
