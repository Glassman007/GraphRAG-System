from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from typing import Any
from urllib.parse import quote, urlsplit

from backend.app.ingestion.adapters.base import FixtureJsonAdapter, checksum_payload, credential_values
from backend.app.ingestion.adapters.github_http import GitHubApiError, GitHubHttpClient
from backend.app.ingestion.models import AdapterPage, ArtifactPayload, ArtifactType, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso

# Preserve the adapter's injectable transport boundary.
ConfiguredJsonHttpClient = GitHubHttpClient
_SHA = re.compile(r"[a-fA-F0-9]{40}")


def parse_repository(value: str) -> tuple[str, str]:
    """Accept github.com HTTPS repository URLs or owner/repo, never arbitrary URLs."""
    value = str(value).strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
                or parsed.query or parsed.fragment):
            raise ValueError("Repository must be a github.com HTTPS URL or owner/repo")
        value = parsed.path.strip("/")
    else:
        value = value.rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if (len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", parts[0])
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", parts[1]) or parts[1] in {".", ".."}):
        raise ValueError("Repository must contain a valid owner and repository name")
    return parts[0].lower(), parts[1].lower()


def _file_path(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value
            or any(ord(c) < 32 for c in value) or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise ValueError("Selected files must be relative repository paths without traversal")
    return value


class GitHubAdapter(FixtureJsonAdapter):
    source_type = "github"
    adapter_version = "github-v2"

    def _options(self) -> dict[str, Any]:
        return {**self.config.connection_config, **self.config.settings, **self.config.scope_config}

    def _repository(self) -> str | None:
        opts = self._options()
        value = opts.get("repository") or opts.get("repository_url")
        if not value and (opts.get("owner") or opts.get("repo")):
            value = f"{opts.get('owner', '')}/{opts.get('repo', '')}"
        return "/".join(parse_repository(value)) if value else None

    def _files(self) -> list[str]:
        values = self._options().get("files", [])
        if not isinstance(values, list):
            raise ValueError("files must be a list of relative repository paths")
        return sorted({_file_path(v) for v in values})

    def _token(self) -> str | None:
        if self._options().get("anonymous") is True:
            return None
        return credential_values(self.config).get("token") or os.getenv(str(self.config.settings.get("token_env") or "GITHUB_TOKEN"))

    def _client(self):
        token = self._token()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return ConfiguredJsonHttpClient(base_url=self.config.base_url or "https://api.github.com", headers=headers)

    def _org(self) -> str:
        org = self._options().get("org") or os.getenv("GITHUB_ORG") or ""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", str(org)):
            raise ValueError("Configure repository (owner/repo or URL) or a valid org")
        return str(org)

    @staticmethod
    def _sha(value: Any) -> str:
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise GitHubApiError("INVALID_RESPONSE", "GitHub response is missing a valid object SHA.")
        return value.lower()

    def _snapshot(self, client, repository: str, *, pinned: str | None = None, pinned_ref: str | None = None) -> dict[str, Any]:
        repo = client.get_json(f"/repos/{repository}")
        if not isinstance(repo, dict) or not repo.get("full_name") or repo.get("id") is None:
            raise GitHubApiError("INVALID_RESPONSE", "GitHub returned invalid repository metadata.")
        requested_ref = pinned_ref or self._options().get("ref") or self._options().get("branch") or repo.get("default_branch")
        if not isinstance(requested_ref, str) or not requested_ref or len(requested_ref) > 1024 or any(ord(c) < 32 for c in requested_ref):
            raise ValueError("Repository requires a valid branch or commit ref")
        commit = client.get_json(f"/repos/{repository}/commits/{quote(pinned or requested_ref, safe='')}")
        if not isinstance(commit, dict) or not isinstance(commit.get("commit"), dict):
            raise GitHubApiError("INVALID_RESPONSE", "GitHub returned invalid commit metadata.")
        sha = self._sha(commit.get("sha"))
        if pinned and sha != pinned:
            raise GitHubApiError("INVALID_RESPONSE", "GitHub returned a different commit than requested.")
        tree_sha = self._sha((commit["commit"].get("tree") or {}).get("sha"))
        return {"repository": repository, "repo": repo, "ref": requested_ref,
                "branch": None if _SHA.fullmatch(requested_ref) else requested_ref,
                "commit_sha": sha, "tree_sha": tree_sha}

    def health_check(self) -> dict[str, Any]:
        if self.config.fixture_path:
            return super().health_check()
        base = {"source_id": self.config.id, "live": True}
        try:
            client = self._client()
            repository = self._repository()
            if repository:
                snapshot = self._snapshot(client, repository)
                details = {k: snapshot[k] for k in ("repository", "ref", "branch", "commit_sha")}
            else:
                org = self._org()
                result = client.get_json(f"/orgs/{org}/repos", query={"per_page": 1, "page": 1})
                if not isinstance(result, list):
                    raise GitHubApiError("INVALID_RESPONSE", "GitHub returned invalid repository discovery data.")
                details = {"org": org}
            return {**base, **details, "ok": True, "status": "HEALTHY", "configured": True,
                    "message": "GitHub repository access verified." if repository else "GitHub organization discovery verified.",
                    "checks": {"authentication": "PASS" if self._token() else "NOT_REQUIRED",
                               "reachability": "PASS", "required_permission": "PASS", "api_access": "PASS"}}
        except GitHubApiError as exc:
            return {**base, "ok": False, "status": exc.code, "message": str(exc),
                    "http_status": exc.status, "retry_after": exc.retry_after, "rate_limit_reset": exc.rate_limit_reset,
                    "checks": {"authentication": "FAIL" if exc.code == "AUTH_FAILED" else "UNKNOWN",
                               "reachability": "PASS" if exc.status is not None else "FAIL",
                               "required_permission": "UNKNOWN", "api_access": "FAIL"}}
        except ValueError:
            return {**base, "ok": False, "status": "CONFIGURATION_ERROR", "message": "Invalid GitHub repository or connector configuration."}
        except (ConnectionError, OSError):
            return {**base, "ok": False, "status": "UNREACHABLE", "message": "GitHub could not be reached."}

    def _tree(self, client, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        result = client.get_json(f"/repos/{snapshot['repository']}/git/trees/{snapshot['tree_sha']}", query={"recursive": "1"})
        if not isinstance(result, dict) or not isinstance(result.get("tree"), list):
            raise GitHubApiError("INVALID_RESPONSE", "GitHub returned invalid tree data.")
        if result.get("truncated"):
            raise GitHubApiError("TREE_TRUNCATED", "GitHub tree is truncated; narrow the source or use a smaller repository.")
        files = []
        for row in result["tree"]:
            if not isinstance(row, dict):
                raise GitHubApiError("INVALID_RESPONSE", "GitHub returned an invalid tree entry.")
            if row.get("type") == "blob" and row.get("mode") in {"100644", "100755"}:
                path = _file_path(row.get("path"))
                files.append({"path": path, "blob_sha": self._sha(row.get("sha")), "size": row.get("size")})
        return sorted(files, key=lambda row: row["path"])

    def discover_files(self) -> dict[str, Any]:
        """Discover regular files at one immutable commit, without downloading blobs."""
        repository = self._repository()
        if not repository:
            raise ValueError("File discovery requires an explicit repository")
        client = self._client()
        snapshot = self._snapshot(client, repository)
        return {**{k: v for k, v in snapshot.items() if k != "repo"}, "files": self._tree(client, snapshot)}

    def _scope(self, mode: str) -> str:
        options = self._options()
        return checksum_payload({"mode": mode, "repository": self._repository(), "files": self._files(),
                                 "ref": options.get("ref") or options.get("branch"),
                                 "org": self._org().lower() if mode == "organization" else None,
                                 "selected": sorted({str(v).lower() for v in self.config.scope_config.get("selected", [])}),
                                 "base_url": self.config.base_url or "https://api.github.com"})

    def _cursor(self, mode: str, **position) -> str:
        return json.dumps({"v": 2, "mode": mode, "scope": self._scope(mode), **position}, separators=(",", ":"), sort_keys=True)

    def _position(self, cursor: str | None, mode: str) -> dict[str, Any]:
        if not cursor:
            return {}
        # Legacy org page cursors remain readable. New cursors use a fixed
        # upstream page size and record offset independent of the caller's limit.
        if mode == "organization" and cursor.isdigit():
            return {"page": max(1, int(cursor)), "offset": 0}
        try:
            value = json.loads(cursor)
            if value["v"] != 2 or value["mode"] != mode or value["scope"] != self._scope(mode):
                raise ValueError()
            if type(value["offset"]) is not int or value["offset"] < 0:
                raise ValueError()
            if mode == "organization" and (type(value["page"]) is not int or value["page"] < 1 or value["offset"] >= 100):
                raise ValueError()
            if mode == "repository":
                self._sha(value["commit"])
                if not isinstance(value["ref"], str) or not value["ref"]:
                    raise ValueError()
            return value
        except (ValueError, KeyError, TypeError, GitHubApiError):
            raise ValueError("Invalid or incompatible GitHub cursor; start a full sync after changing scope") from None

    def _repository_record(self, repo: dict[str, Any], *, cursor: str, snapshot: dict[str, Any] | None = None) -> SourceRecordEnvelope:
        raw = {"name": repo.get("name"), "full_name": repo.get("full_name"), "html_url": repo.get("html_url"),
               "owner": (repo.get("owner") or {}).get("login"), "language": repo.get("language"), "default_branch": repo.get("default_branch")}
        if snapshot:
            raw.update({k: snapshot[k] for k in ("branch", "ref", "commit_sha", "tree_sha")})
        return SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance,
                                    external_id=str(repo["id"]), record_type="repository", observed_at=repo.get("updated_at"),
                                    fetched_at=now_iso(), source_updated_at=repo.get("updated_at"), raw_metadata=raw,
                                    canonical_source_uri=repo.get("html_url"), cursor=cursor, checksum=checksum_payload(raw),
                                    version=snapshot["commit_sha"] if snapshot else None)

    def _file_record(self, client, snapshot: dict[str, Any], file: dict[str, Any], cursor: str) -> SourceRecordEnvelope:
        max_bytes = self._options().get("max_file_bytes", 20 * 1024 * 1024)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 20 * 1024 * 1024:
            raise ValueError("max_file_bytes must be between 1 and 20971520")
        if type(file["size"]) is not int or file["size"] < 0:
            raise GitHubApiError("INVALID_RESPONSE", "GitHub file size is missing or invalid.")
        if file["size"] > max_bytes:
            raise GitHubApiError("FILE_TOO_LARGE", "Selected GitHub file exceeds the configured size limit.")
        blob = client.get_json(f"/repos/{snapshot['repository']}/git/blobs/{file['blob_sha']}")
        try:
            if blob.get("encoding") != "base64" or blob.get("sha") != file["blob_sha"]:
                raise ValueError()
            content = base64.b64decode("".join(blob["content"].split()), validate=True)
        except (ValueError, KeyError, AttributeError, TypeError, binascii.Error):
            raise GitHubApiError("INVALID_RESPONSE", "GitHub returned invalid blob content.") from None
        blob_hash = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if len(content) != file["size"] or blob_hash != file["blob_sha"]:
            raise GitHubApiError("INVALID_RESPONSE", "GitHub blob content does not match its declared size and SHA.")
        url = f"https://github.com/{snapshot['repository']}/blob/{snapshot['commit_sha']}/{quote(file['path'], safe='/')}"
        raw = {**file, **{k: snapshot[k] for k in ("repository", "branch", "ref", "commit_sha")},
               "html_url": url, "sha256": hashlib.sha256(content).hexdigest()}
        return SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance,
                                    external_id=f"{snapshot['repository']}:{file['path']}",
                                    record_type="sql_file" if file["path"].lower().endswith(".sql") else "source_file",
                                    fetched_at=now_iso(), version=snapshot["commit_sha"], raw_metadata=raw,
                                    canonical_source_uri=url, cursor=cursor, checksum=checksum_payload(raw),
                                    artifacts=[ArtifactPayload(name=file["path"], content=content,
                                                              artifact_type=ArtifactType.SOURCE_FILE, external_uri=url)])

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("GitHub fetch limit must be between 1 and 10000")
        repository = self._repository()
        client = self._client()
        if not repository:
            if self._files():
                raise ValueError("Selected files require an explicit repository")
            return self._fetch_organization(client, cursor, limit)
        position = self._position(cursor, "repository")
        snapshot = self._snapshot(client, repository, pinned=position.get("commit"), pinned_ref=position.get("ref"))
        selected = self._files()
        files = {row["path"]: row for row in self._tree(client, snapshot)} if selected else {}
        if any(path not in files for path in selected):
            raise GitHubApiError("NOT_FOUND", "A selected file is missing or is not a regular file at the pinned commit.")
        start = position.get("offset", 0)
        total = 1 + len(selected)
        if start > total:
            raise ValueError("GitHub cursor is beyond the selected records")
        records = []
        for offset in range(start, min(total, start + limit)):
            nxt = self._cursor("repository", commit=snapshot["commit_sha"], ref=snapshot["ref"], offset=offset + 1)
            records.append(self._repository_record(snapshot["repo"], cursor=nxt, snapshot=snapshot) if offset == 0
                           else self._file_record(client, snapshot, files[selected[offset - 1]], nxt))
        nxt = self._cursor("repository", commit=snapshot["commit_sha"], ref=snapshot["ref"], offset=start + len(records))
        return AdapterPage(records=records, next_cursor=nxt, has_more=start + len(records) < total)

    def _fetch_organization(self, client, cursor: str | None, limit: int) -> AdapterPage:
        org = self._org()
        position = self._position(cursor, "organization")
        page, offset = position.get("page", 1), position.get("offset", 0)
        selected = {str(v).lower() for v in self.config.scope_config.get("selected", [])}
        records = []
        for _ in range(100):
            repos = client.get_json(f"/orgs/{org}/repos", query={"per_page": 100, "page": page, "sort": "full_name", "direction": "asc"})
            if (not isinstance(repos, list) or len(repos) > 100
                    or any(not isinstance(r, dict) or r.get("id") is None or not r.get("full_name") for r in repos)):
                raise GitHubApiError("INVALID_RESPONSE", "GitHub returned invalid repository discovery data.")
            for index in range(offset, len(repos)):
                repo = repos[index]
                next_page, next_offset = (page + 1, 0) if index + 1 == len(repos) else (page, index + 1)
                if selected and str(repo.get("name", "")).lower() not in selected and str(repo.get("full_name", "")).lower() not in selected:
                    continue
                nxt = self._cursor("organization", page=next_page, offset=next_offset)
                records.append(self._repository_record(repo, cursor=nxt))
                if len(records) >= limit:
                    return AdapterPage(records=records, next_cursor=nxt, has_more=index + 1 < len(repos) or len(repos) == 100)
            if len(repos) < 100:
                return AdapterPage(records=records, next_cursor=self._cursor("organization", page=page + 1, offset=0), has_more=False)
            page, offset = page + 1, 0
        raise GitHubApiError("DISCOVERY_LIMIT", "GitHub organization discovery exceeded 100 pages; use explicit repository scope.")
