from __future__ import annotations

import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    falkordb_host: str = Field(default="localhost")
    falkordb_port: int = Field(default=6379, ge=1, le=65535)
    falkordb_graph: str = Field(default="company_brain", min_length=1)
    falkordb_password: str | None = None
    tenant_id: str = Field(default="northstar", min_length=1)

    @classmethod
    def from_env(cls) -> "Settings":
        password = os.getenv("FALKORDB_PASSWORD") or None
        return cls(
            falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
            falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
            falkordb_graph=os.getenv("FALKORDB_GRAPH", "company_brain"),
            falkordb_password=password,
            tenant_id=os.getenv("GRAPH_TENANT_ID", "northstar"),
        )
