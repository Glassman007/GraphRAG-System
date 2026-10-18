from __future__ import annotations

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.retrieval.models import GraphScope, RetrievalPlan, RetrievalRequest, RetrievalResult
from backend.app.retrieval.utils import stable_hash
from backend.app.services.phase6_utils import now_iso


class RetrievalEvidenceService:
    def __init__(self,client:FalkorGraphClient):self.client=client

    @staticmethod
    def _edge_id(source_id:str,rel_type:str,target_id:str,semantic:str="")->str:
        return stable_hash(source_id,rel_type,target_id,semantic,prefix="RETEDGE")

    def _link(self,source_id:str,rel_type:str,target_id:str,props:dict|None=None,*,semantic:str="")->None:
        values=dict(props or {})
        values["edge_id"]=self._edge_id(source_id,rel_type,target_id,semantic)
        upsert_relationship(self.client,source_id,rel_type,target_id,values)

    def persist(self,request:RetrievalRequest,scope:GraphScope,plan:RetrievalPlan,results:list[RetrievalResult])->tuple[str,list[str]]:
        mode_key="|".join(m.value for m in plan.modes)
        execution_id=stable_hash(
            request.tenant_id,request.query,request.task_id,request.investigation_id,request.as_of,
            plan.graph_scope_hash,mode_key,request.max_results,request.metadata_filters,request.evidence_requirements,
            prefix="RETRIEVAL",
        )
        at=now_iso()
        from backend.app.services.phase4_graph import GraphSnapshot
        before=GraphSnapshot.load(self.client)
        prior_execution=before.node(execution_id) or {}
        started_at=prior_execution.get("started_at") or at
        upsert_node(self.client,"RetrievalExecution",execution_id,{"query":request.query,"status":"SUCCEEDED","started_at":started_at,"completed_at":at,"graph_scope_hash":plan.graph_scope_hash,"as_of":request.as_of,"retrievers_used":mode_key,"result_count":len(results)})
        if request.requesting_agent_id:self._link(execution_id,"REQUESTED_BY",request.requesting_agent_id,{"valid_from":started_at})
        if request.task_id:self._link(execution_id,"FOR_TASK",request.task_id,{"valid_from":started_at})
        if request.investigation_id:self._link(request.investigation_id,"HAS_RETRIEVAL",execution_id,{"valid_from":started_at})
        evidence_ids=[]
        for result in results:
            origin=result.chunk_id or result.artifact_id or result.source_record_id or result.document_id or result.result_id
            # Evidence identity is the retrieved source observation in this query/scope context,
            # not the particular lexical/vector execution that happened to surface it.
            eid=stable_hash(request.tenant_id,request.query,request.task_id,request.investigation_id,request.as_of,plan.graph_scope_hash,origin,result.observed_at,prefix="EVID-RET")
            prior_evidence=before.node(eid) or {}
            evidence_created_at=prior_evidence.get("created_at") or at
            upsert_node(self.client,"Evidence",eid,{"content":result.text,"statement":result.text,"status":"UNVERIFIED","evidence_type":"RETRIEVED","retrieval_method":result.retrieval_method.value,"retrieval_score":result.score,"query":request.query,"observed_at":result.observed_at or evidence_created_at,"created_at":evidence_created_at,"source_ref_id":result.source_record_id or result.artifact_id,"retrieval_execution_id":execution_id})
            self._link(execution_id,"RETURNED",eid,{"valid_from":started_at,"retrieval_method":result.retrieval_method.value,"rank":result.rank,"retrieval_score":result.score},semantic=result.retrieval_method.value)
            if request.requesting_agent_id:
                self._link(request.requesting_agent_id,"PRODUCED",eid,{"valid_from":evidence_created_at,"production_mode":"retrieval"},semantic="retrieval")
            if request.task_id:self._link(eid,"ABOUT",request.task_id,{"valid_from":evidence_created_at,"scope":"retrieval_task"},semantic="retrieval_task")
            if request.investigation_id:self._link(eid,"ABOUT",request.investigation_id,{"valid_from":evidence_created_at,"scope":"retrieval_investigation"},semantic="retrieval_investigation")
            for target in (result.chunk_id,result.artifact_id,result.source_record_id):
                if target:self._link(eid,"DERIVED_FROM",target,{"valid_from":evidence_created_at,"retrieval_method":result.retrieval_method.value},semantic=str(target))
            if result.source_id:
                self._link(execution_id,"USED_SOURCE",result.source_id,{"valid_from":started_at})
                self._link(eid,"DERIVED_FROM",result.source_id,{"valid_from":evidence_created_at,"provenance_role":"data_source"},semantic="data_source")
            for mid in result.matched_entity_ids[:20]:
                self._link(eid,"ABOUT",mid,{"valid_from":evidence_created_at,"scope":"retrieval_match"},semantic="retrieval_match")
            evidence_ids.append(eid)
        return execution_id,evidence_ids
