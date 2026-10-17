from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from backend.app.retrieval.models import IndexedDocument
from backend.app.retrieval.utils import content_hash, stable_hash


@dataclass
class ChunkingConfig:
    max_chars: int = 1200
    overlap_chars: int = 120
    version: str = "phase10-chunk-v1"


class DocumentChunker:
    def __init__(self, config: ChunkingConfig | None = None): self.config=config or ChunkingConfig()
    def _sections(self,text:str,document_type:str)->list[tuple[str,str]]:
        if document_type.upper() in {"JSON","JSON_PAYLOAD"}:
            try:
                value=json.loads(text)
                if isinstance(value,dict): return [(str(k),json.dumps(v,sort_keys=True,ensure_ascii=False)) for k,v in value.items()]
            except Exception: pass
        lines=text.splitlines(); sections=[]; heading=""
        buffer=[]
        for line in lines:
            if re.match(r"^#{1,6}\s+",line):
                if buffer: sections.append((heading,"\n".join(buffer).strip()));buffer=[]
                heading=re.sub(r"^#{1,6}\s+","",line).strip();continue
            if not line.strip() and buffer:
                sections.append((heading,"\n".join(buffer).strip()));buffer=[]
            else: buffer.append(line)
        if buffer:sections.append((heading,"\n".join(buffer).strip()))
        return [(h,b) for h,b in sections if b] or [("",text)]
    def chunk(self,*,document_id:str,text:str,tenant_id:str,artifact_id:str|None=None,source_record_id:str|None=None,data_source_id:str|None=None,entity_ids:list[str]|None=None,document_type:str="TEXT",observed_at:str|None=None,metadata:dict[str,Any]|None=None)->list[IndexedDocument]:
        out=[];seq=0
        for heading,body in self._sections(text,document_type):
            start=0
            while start<len(body):
                end=min(len(body),start+self.config.max_chars); piece=body[start:end]
                cid=stable_hash(document_id,seq,content_hash(piece),self.config.version,prefix="CHUNK")
                out.append(IndexedDocument(document_id=cid,text=piece,tenant_id=tenant_id,artifact_id=artifact_id,source_record_id=source_record_id,data_source_id=data_source_id,entity_ids=list(entity_ids or []),document_type="CHUNK",observed_at=observed_at,content_hash=content_hash(piece),metadata={**(metadata or {}),"parent_document_id":document_id,"sequence":seq,"heading":heading,"char_start":start,"char_end":end,"chunking_version":self.config.version}))
                seq+=1
                if end>=len(body):break
                start=max(start+1,end-self.config.overlap_chars)
        return out
