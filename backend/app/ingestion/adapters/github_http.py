"""Bounded GitHub JSON transport with safe, actionable errors."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GitHubApiError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None,
                 retry_after: str | None = None, rate_limit_reset: str | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after
        self.rate_limit_reset = rate_limit_reset


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward connector credentials to a redirect target.
        return None


class GitHubHttpClient:
    def __init__(self, *, base_url: str, headers: dict[str, str] | None = None,
                 timeout: float = 10.0, max_response_bytes: int = 32 * 1024 * 1024):
        parsed = urllib.parse.urlsplit(base_url)
        allowed = {v.strip().lower() for v in os.getenv(
            "GRAPH_HACKS_ALLOWED_CONNECTOR_HOSTS", "api.github.com,github.com,slack.com"
        ).split(",") if v.strip()}
        if (parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("GitHub API base URL must be HTTPS on a server-allowed host without credentials or query")
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": "VERINEX-GitHub-Connector", "Accept": "application/vnd.github+json", **(headers or {})}
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self._opener = urllib.request.build_opener(_NoRedirect())

    def get_json(self, path: str, *, query: dict[str, Any] | None = None) -> Any:
        url = self.base_url + "/" + path.lstrip("/")
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers=self.headers, method="GET")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                payload = response.read(self.max_response_bytes + 1)
            if len(payload) > self.max_response_bytes:
                raise GitHubApiError("RESPONSE_TOO_LARGE", "GitHub response exceeds the configured size limit.")
            return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            headers = exc.headers or {}
            with exc:
                body = exc.read(4096).lower()
            limited = (exc.code == 429 or (exc.code == 403 and (
                headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After")
                or b"rate limit" in body or b"secondary rate" in body)))
            if limited:
                code, message = "RATE_LIMITED", "GitHub rate limit reached; retry after the indicated reset."
            else:
                code, message = {
                    401: ("AUTH_FAILED", "GitHub rejected the configured credential."),
                    403: ("PERMISSION_ERROR", "GitHub denied access to this resource."),
                    404: ("NOT_FOUND", "GitHub repository, ref or file was not found or is not accessible."),
                }.get(exc.code, ("API_ERROR", f"GitHub API request failed (HTTP {exc.code})."))
            raise GitHubApiError(code, message, status=exc.code,
                                 retry_after=headers.get("Retry-After"),
                                 rate_limit_reset=headers.get("X-RateLimit-Reset")) from None
        except (TimeoutError, socket.timeout):
            raise GitHubApiError("TIMEOUT", "GitHub request timed out.") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise GitHubApiError("TIMEOUT", "GitHub request timed out.") from None
            raise GitHubApiError("UNREACHABLE", "GitHub could not be reached.") from None
        except (ConnectionError, OSError):
            raise GitHubApiError("UNREACHABLE", "GitHub could not be reached.") from None
        except (ValueError, UnicodeError):
            raise GitHubApiError("INVALID_RESPONSE", "GitHub returned an invalid JSON response.") from None
