"""Keep filesystem retrieval indexes isolated between registered Company Brains."""
from __future__ import annotations

import os
from pathlib import Path

def scoped_index_root(*, tenant_id: str, graph_id: str, root: Path) -> Path:
    """Preserve historical company_brain index path; segregate other graphs.

    Tenant and graph are validated at the authenticated API/registry boundary.
    No dynamic path components are accepted from unauthenticated requests.
    """
    base = Path(os.getenv('GRAPH_HACKS_RETRIEVAL_ROOT') or root / '.graphhacks_retrieval')
    if graph_id == 'company_brain':
        return base / tenant_id
    return base / tenant_id / 'brains' / graph_id
