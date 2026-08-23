import os
import json
import dataclasses
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from google import genai
from google.genai import types

from data_layer import Session
from evidence_curation import DecisionContext


class ToolCall(BaseModel):
    name: str
    arguments: Any


class LLM1Response(BaseModel):
    intent: str
    ambiguous: bool
    extracted_facts: Any
    tool_calls: List[ToolCall]


class LLM2Response(BaseModel):
    answer_type: str
    text: str


class LLMClient:
    def __init__(self):
        self.mode = os.environ.get("LLM_MODE", "gemini")
        if self.mode == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY is required when LLM_MODE=gemini")
            self.client = genai.Client(api_key=api_key)
            self.model_id = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    def llm1_classifier(self, text: str, session: Session) -> Dict[str, Any]:
        if self.mode == "mock":
            # Naive mock for testing UI/API without API key
            intent = "unrecognized"
            text_lower = text.lower()
            if "cancel" in text_lower:
                intent = "cancellation_query"
            elif "credit" in text_lower or "late" in text_lower:
                intent = "credit_query"
            elif "sla" in text_lower or "urgent" in text_lower:
                intent = "sla_query"
            elif "status" in text_lower:
                intent = "status_query"
                
            return {
                "intent": intent,
                "ambiguous": False,
                "extracted_facts": {},
                "tool_calls": []
            }
            
        prompt = f"""
You are an intent classification and fact extraction engine for a logistics customer support system.
Current session role: {session.role}
Account ID: {session.account_id}

User input: "{text}"

Classify the intent into one of: cancellation_query, credit_query, sla_query, status_query, unrecognized.
If the intent could mean multiple things, set ambiguous to true.
Extract facts mentioned in the text (e.g., order_id, delay_hours, carrier_fault, customer_fault).
If a tool call is needed to retrieve data, emit it in tool_calls.
Allowed tools: search_documents, get_order, get_cancellation_terms, get_credit_terms, evaluate_sla, prepare_action.
"""
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LLM1Response,
                temperature=0.1
            )
        )
        if not response.text:
            raise RuntimeError("Gemini returned empty response for LLM1")
        result = json.loads(response.text)
        # Normalize extracted_facts to dict
        if not isinstance(result.get("extracted_facts"), dict):
            result["extracted_facts"] = {}
        # Normalize tool_calls to list
        if not isinstance(result.get("tool_calls"), list):
            result["tool_calls"] = []
        return result

    def _serialize_dc(self, obj: Any) -> Any:
        if dataclasses.is_dataclass(obj):
            return {f.name: self._serialize_dc(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        if isinstance(obj, tuple):
            return [self._serialize_dc(x) for x in obj]
        if isinstance(obj, list):
            return [self._serialize_dc(x) for x in obj]
        if isinstance(obj, dict) or str(type(obj)) == "<class 'mappingproxy'>":
            return {k: self._serialize_dc(v) for k, v in dict(obj).items()}
        return obj

    def llm2_reasoner(self, dc: DecisionContext) -> Dict[str, Any]:
        if self.mode == "mock":
            return {
                "answer_type": dc.evidence_status if dc.evidence_status == "HUMAN_REVIEW" else "ANSWER",
                "text": "This is a mocked answer from LLM_MODE=mock."
            }
        
        dc_dict = self._serialize_dc(dc)
        
        prompt = f"""
You are a decision reasoner for a logistics support system. 
Use the following Decision Context to answer the user's query.

Decision Context:
{json.dumps(dc_dict, indent=2)}

Rules:
1. If evidence_status is HUMAN_REVIEW, set answer_type to HUMAN_REVIEW and explain what information is missing.
2. Otherwise, set answer_type to ANSWER and provide a concise, factual response citing the provided facts and computed_results.
3. Do not invent information outside the Decision Context.
4. Do not override computed_results with your own calculations.
5. Always cite the source documents referenced in the facts.
"""
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LLM2Response,
                temperature=0.1
            )
        )
        if not response.text:
            raise RuntimeError("Gemini returned empty response for LLM2")
        return json.loads(response.text)
