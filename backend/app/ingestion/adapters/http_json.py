from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class ConfiguredJsonHttpClient:
    """Read-only JSON HTTP client. URLs come from server-side SourceConfig only."""

    def __init__(self, *, base_url: str, headers: dict[str, str] | None = None, timeout: float = 10.0):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Configured source base_url must be an absolute HTTP(S) URL")
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = timeout

    def get_json(self, path: str, *, query: dict[str, Any] | None = None) -> Any:
        # path is adapter-owned, not user-provided through a public endpoint.
        path = "/" + path.lstrip("/")
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        request = urllib.request.Request(url, headers=self.headers, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec - URL is server configured
            return json.loads(response.read().decode("utf-8"))
