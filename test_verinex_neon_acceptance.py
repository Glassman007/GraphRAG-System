"""RED tests for desired VERINEX Neon GitHub integration capabilities.
Execute from project root: PYTHONPATH=. pytest -q /mnt/data/test_verinex_neon_acceptance.py
Requires: pytest, pydantic. Does NOT require remote access or FalkorDB.
"""
import os
from unittest.mock import patch
import pytest

from backend.app.ingestion.models import SourceConfig, SourceRecordEnvelope
from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.ingestion.adapters.database import DatabaseAdapter
from backend.app.ingestion.normalization.github import GitHubNormalizer
from backend.app.ingestion.normalization.database import DatabaseNormalizer
from backend.app.ingestion.adapters import github as github_module

REPO = 'neondatabase/postgres-sample-dbs'

def config(*, token=True, selected=None, org='neondatabase'):
    # token=True -> simulate injected credential via mocked credential_values below
    return SourceConfig(id='TEST-NEON', source_type='github', name='Neon Sample DBs',
                        source_instance='neon-samples', base_url='https://api.github.com',
                        settings={'org': org}, scope_config={'selected': selected or [REPO]})

def repo_row(name='postgres-sample-dbs'):
    return {'id': 123456, 'name': name, 'full_name': f'neondatabase/{name}',
            'html_url': f'https://github.com/neondatabase/{name}',
            'owner': {'login': 'neondatabase'}, 'language': 'SQL',
            'updated_at': '2026-10-18T12:00:00Z'}

def env(record_type, raw):
    return SourceRecordEnvelope(source_type='github', source_instance='neon-samples',
      external_id='123456', record_type=record_type, fetched_at='2026-10-21T12:00:00Z',
      raw_metadata=raw, checksum='abc')

def test_01_public_repository_can_be_checked_without_token(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.setattr(github_module, 'credential_values', lambda cfg: {})
    assert GitHubAdapter(config()).health_check()['ok'], 'Public repo discovery should not require PAT'

def test_02_health_check_rejects_unreachable_host(monkeypatch):
    monkeypatch.setattr(github_module, 'credential_values', lambda cfg: {'token': 'invalid'})
    class RemoteDown:
        def __init__(self, *args, **kwargs): pass
        def get_json(self, *args, **kwargs): raise ConnectionError('fake remote unreachable')
    monkeypatch.setattr(github_module, 'ConfiguredJsonHttpClient', RemoteDown)
    assert not GitHubAdapter(config()).health_check()['ok'], 'Health should exercise the remote GitHub API'

def test_03_single_repository_fetch_uses_exact_repo_endpoint(monkeypatch):
    monkeypatch.setattr(github_module, 'credential_values', lambda cfg: {'token': 'fake'})
    calls = []
    class FakeHTTP:
        def __init__(self, **kw): pass
        def get_json(self, path, query=None):
            calls.append((path, query))
            if path == '/repos/neondatabase/postgres-sample-dbs': return repo_row()
            return []
    monkeypatch.setattr(github_module, 'ConfiguredJsonHttpClient', FakeHTTP)
    page = GitHubAdapter(config()).fetch(limit=20)
    assert any(path == '/repos/neondatabase/postgres-sample-dbs' for path, _ in calls), calls
    assert len(page.records) == 1

def test_04_filtered_pages_do_not_stop_before_matching_repository(monkeypatch):
    monkeypatch.setattr(github_module, 'credential_values', lambda cfg: {'token': 'fake'})
    class FakeHTTP:
        def __init__(self, **kw): pass
        def get_json(self, path, query=None):
            if query['page'] == 1: return [repo_row('unrelatedA'), repo_row('unrelatedB')]
            return [repo_row()]
    monkeypatch.setattr(github_module, 'ConfiguredJsonHttpClient', FakeHTTP)
    page = GitHubAdapter(config()).fetch(cursor='1', limit=2)
    assert page.has_more, 'Raw first page full: next page must not be dropped after post-filtering'

def test_05_github_sql_file_maps_to_repo_and_dataset():
    # Desired new live adapter record type for a fetched SQL file.
    normalized = GitHubNormalizer(config()).normalize('SRC-1', env('sql_file', {
       'repository': REPO, 'path': 'dvdrental.sql',
       'html_url': f'https://github.com/{REPO}/blob/main/dvdrental.sql',
       'sha': 'deterministic-test-sha', 'dataset': 'dvdrental'}))
    assert len(normalized.entities) >= 2, 'At least repository and SQL-file/dataset entity expected'
    assert len(normalized.relations) >= 1, 'Graph must have repo->file/schema relationships'

def test_06_database_connector_health_requires_real_credentials(monkeypatch):
    monkeypatch.delenv('INGESTION_DATABASE_DSN', raising=False)
    monkeypatch.delenv('NEON_TEST_DATABASE_DSN', raising=False)
    from backend.app.ingestion.adapters import database as dbmodule
    monkeypatch.setattr(dbmodule, 'credential_values', lambda cfg: {})
    cfg = SourceConfig(id='DB', source_type='database', name='db', source_instance='db',
                       settings={'dsn_env': 'NEON_TEST_DATABASE_DSN', 'query': 'SELECT 1', 'cursor_column': 'id'})
    assert not DatabaseAdapter(cfg).health_check()['ok'], 'An env-var NAME is not a database connection'

def test_07_sql_table_records_do_not_vanish_into_unmapped_warning():
    cfg = SourceConfig(id='DB', source_type='database', name='db', source_instance='db')
    record = SourceRecordEnvelope(source_type='database', source_instance='db',
      external_id='dvdrental.public.payment', record_type='table', fetched_at='2026-10-21T12:00:00Z',
      raw_metadata={'schema':'public','table':'payment','database':'dvdrental'}, checksum='abc')
    norm = DatabaseNormalizer(cfg).normalize('SRC-TBL', record)
    assert norm.entities, f'Schema discovery record should create canonical entities; warnings={norm.warnings}'
