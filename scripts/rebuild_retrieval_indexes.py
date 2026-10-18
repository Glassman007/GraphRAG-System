from __future__ import annotations

import os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.retrieval.indexing import RetrievalIndexer
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex


def main()->None:
    client=FalkorGraphClient()
    index_root=Path(os.getenv("GRAPH_HACKS_RETRIEVAL_ROOT") or ROOT/".graphhacks_retrieval")/client.settings.tenant_id
    artifact_root=Path(os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or ROOT/".graphhacks_artifacts")
    indexer=RetrievalIndexer(client,lexical=BM25LexicalIndex(index_root/"lexical.json"),vector=LocalVectorIndex(path=index_root/"vector.json"),artifact_store=LocalArtifactStore(artifact_root))
    result=indexer.rebuild()
    print(f"Retrieval indexes rebuilt for graph={client.settings.falkordb_graph} tenant={client.settings.tenant_id}")
    print(result)

if __name__=="__main__":main()
