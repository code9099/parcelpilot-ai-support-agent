from dotenv import load_dotenv
load_dotenv()
import os
import contextvars
import dataclasses
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from orchestrator import Orchestrator
from llm_client import LLMClient

app = FastAPI(title="Logistics AI Demo")

DEMO_PROFILES = {
    "NORTHSTAR": {"role": "customer", "account_id": "ACCT-001"},
    "LUMENWORKS": {"role": "customer", "account_id": "ACCT-002"},
    "OPS": {"role": "internal", "account_id": None},
}

llm_client = LLMClient()
orchestrator = Orchestrator()

# Use contextvars to safely capture trace data across async requests
request_trace_var = contextvars.ContextVar('request_trace', default={})

def wrapped_llm1(text, session):
    res = llm_client.llm1_classifier(text, session)
    trace = request_trace_var.get()
    trace['llm1_output'] = res
    return res

def wrapped_llm2(dc):
    trace = request_trace_var.get()
    
    def _serialize(obj):
        if dataclasses.is_dataclass(obj):
            return {f.name: _serialize(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        if isinstance(obj, tuple):
            return [_serialize(x) for x in obj]
        if isinstance(obj, list):
            return [_serialize(x) for x in obj]
        if isinstance(obj, dict) or str(type(obj)) == "<class 'mappingproxy'>":
            return {k: _serialize(v) for k, v in dict(obj).items()}
        return obj

    trace['decision_context'] = _serialize(dc)
    
    res = llm_client.llm2_reasoner(dc)
    trace['llm2_output'] = res
    return res

orchestrator.llm1_classifier = wrapped_llm1
orchestrator.llm2_reasoner = wrapped_llm2


class ChatRequest(BaseModel):
    profile_id: str
    user_text: str
    context_links: Optional[List[Dict[str, Any]]] = None

class ConfirmRequest(BaseModel):
    profile_id: str
    request_id: str


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    if req.profile_id not in DEMO_PROFILES:
        raise HTTPException(status_code=400, detail="Invalid profile_id")
        
    session_dict = DEMO_PROFILES[req.profile_id]
    
    # Ensure context_links cannot override session fields
    safe_context_links = []
    if req.context_links:
        for c in req.context_links:
            # Only allow specific safe keys
            safe_c = {}
            if "context_order_id" in c:
                safe_c["context_order_id"] = str(c["context_order_id"])
            if "context_ticket_id" in c:
                safe_c["context_ticket_id"] = str(c["context_ticket_id"])
            safe_context_links.append(safe_c)
            
    # Reset trace for this request
    request_trace_var.set({})
            
    # Process request
    result = orchestrator.process_request(
        session_dict=session_dict, 
        user_text=req.user_text, 
        context_links=safe_context_links
    )
    
    trace = request_trace_var.get()
    
    # Augment result with trace info for the UI debug sidebar
    if isinstance(result, dict):
        result["_trace"] = {
            "session": session_dict,
            "llm1_output": trace.get("llm1_output", {}),
            "decision_context": trace.get("decision_context", {})
        }
    
    return result

@app.post("/api/action/confirm")
async def api_action_confirm(req: ConfirmRequest):
    if req.profile_id not in DEMO_PROFILES:
        raise HTTPException(status_code=400, detail="Invalid profile_id")
        
    session_dict = DEMO_PROFILES[req.profile_id]
    
    result = orchestrator.confirm_action(req.request_id, session_dict)
    return result

# Serve static UI
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
