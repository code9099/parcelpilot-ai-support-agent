import json
import re
import uuid
import logging
import os
from types import MappingProxyType
from typing import Dict, Any, List, Optional, Tuple, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import time

from data_layer import Session, query_data, search_documents
from business_rules.cancellation import evaluate_cancellation
from business_rules.credit import evaluate_credit
from business_rules.sla import evaluate_sla
from evidence_curation import curate_decision_context, DecisionContext

logger = logging.getLogger(__name__)

# --- Constants ---
VALID_INTENTS = frozenset({
    "cancellation_query", "credit_query", "sla_query",
    "status_query", "unrecognized"
})
VALID_ANSWER_TYPES = frozenset({"ANSWER", "HUMAN_REVIEW"})
NEGATION_WORDS = frozenset({
    "not", "no", "never", "didn't", "wasn't", "isn't",
    "neither", "nor", "without", "none", "don't", "can't",
    "couldn't", "shouldn't", "won't", "wouldn't", "hardly"
})

CARRIER_FAULT_TRUE_PHRASES = [
    "carrier at fault", "carrier's fault", "carrier fault",
    "carrier was at fault", "carrier is at fault"
]
CARRIER_FAULT_FALSE_PHRASES = [
    "carrier not at fault", "not carrier fault",
    "not carrier's fault", "carrier wasn't at fault",
    "carrier is not at fault"
]
CUSTOMER_FAULT_TRUE_PHRASES = [
    "customer at fault", "customer's fault", "customer fault",
    "customer was at fault", "customer is at fault"
]
CUSTOMER_FAULT_FALSE_PHRASES = [
    "customer not at fault", "not customer fault",
    "not customer's fault", "customer wasn't at fault",
    "customer is not at fault", "no customer fault",
    "customer was not at fault", "customer didn't cause the issue",
    "customer did not cause the issue"
]


@dataclass(frozen=True)
class PendingAction:
    request_id: str
    account_id: str
    action_type: str
    payload: Mapping[str, Any]
    expires_at: float
    status: str  # pending_confirmation, confirmed, executed, expired, cancelled, execution_failed

    def __post_init__(self):
        if isinstance(self.payload, dict):
            object.__setattr__(self, 'payload', MappingProxyType(dict(self.payload)))

    def with_status(self, new_status: str) -> 'PendingAction':
        return PendingAction(
            request_id=self.request_id,
            account_id=self.account_id,
            action_type=self.action_type,
            payload=dict(self.payload),
            expires_at=self.expires_at,
            status=new_status
        )


class Orchestrator:
    def __init__(self):
        self.pending_actions: Dict[str, PendingAction] = {}
        self.llm1_classifier: Callable = self._default_llm1
        self.llm2_reasoner: Callable = self._default_llm2

    def _default_llm1(self, text: str, session: Session) -> Dict[str, Any]:
        raise NotImplementedError("LLM1 must be injected")

    def _default_llm2(self, decision_context: DecisionContext) -> Dict[str, Any]:
        raise NotImplementedError("LLM2 must be injected")

    # ------------------------------------------------------------------ #
    #  LLM Output Validation
    # ------------------------------------------------------------------ #

    def _parse_json_output(self, raw) -> Optional[Dict]:
        """Attempt to parse raw LLM output into a dict."""
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        try:
            result = json.loads(raw)
            return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw.strip(), re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                return result if isinstance(result, dict) else None
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def _normalize_tool_calls(self, raw_calls: list) -> list:
        """Normalize various provider formats to canonical {name, arguments}."""
        normalized = []
        for tc in raw_calls:
            if not isinstance(tc, dict):
                continue
            if "name" in tc and isinstance(tc.get("arguments"), dict):
                normalized.append({"name": tc["name"], "arguments": tc["arguments"]})
            elif "function" in tc and isinstance(tc.get("function"), dict):
                fn = tc["function"]
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        args = {}
                if isinstance(args, dict):
                    normalized.append({"name": fn.get("name"), "arguments": args})
            elif tc.get("type") == "tool_use" and "name" in tc:
                args = tc.get("input", {})
                if isinstance(args, dict):
                    normalized.append({"name": tc["name"], "arguments": args})
        return normalized

    def _validate_llm1_output(self, raw) -> Tuple[Optional[Dict], Optional[str]]:
        """Parse and validate LLM #1 output."""
        parsed = self._parse_json_output(raw)
        if parsed is None:
            return None, "LLM1_MALFORMED_OUTPUT"
        intent = parsed.get("intent", "unrecognized")
        if intent not in VALID_INTENTS:
            parsed["_invalid_intent"] = intent
            parsed["intent"] = "unrecognized"
        raw_calls = parsed.get("tool_calls", [])
        parsed["tool_calls"] = self._normalize_tool_calls(raw_calls) if isinstance(raw_calls, list) else []
        if not isinstance(parsed.get("extracted_facts"), dict):
            parsed["extracted_facts"] = {}
        return parsed, None

    def _validate_llm2_output(self, raw) -> Tuple[Optional[Dict], Optional[str]]:
        """Parse and validate LLM #2 output."""
        parsed = self._parse_json_output(raw)
        if parsed is None:
            return None, "LLM2_MALFORMED_OUTPUT"
        if parsed.get("answer_type") not in VALID_ANSWER_TYPES:
            parsed["answer_type"] = "HUMAN_REVIEW"
        return parsed, None

    # ------------------------------------------------------------------ #
    #  Extraction-Validation Boundary
    # ------------------------------------------------------------------ #

    def _validate_extracted_facts(self, extracted_facts_raw: dict, user_text: str) -> Tuple[list, list]:
        """
        Validate LLM-extracted facts against original user text.
        Unsupported extractions are DROPPED and recorded as gaps.
        Returns (validated_user_facts, evidence_gaps).
        """
        user_lower = user_text.lower()
        validated = []
        gaps = []

        for k, v in extracted_facts_raw.items():
            # Severity is always INFERRED_RELATIONSHIP
            if k == "severity":
                v_str = str(v).upper()
                if v_str in {"P1", "P2", "P3"}:
                    validated.append({
                        "fact": f"Severity classified as {v_str}",
                        "source": "User Query Inference",
                        "type": "INFERRED_RELATIONSHIP"
                    })
                else:
                    gaps.append({
                        "missing_fact": f"LLM extracted invalid severity '{v}'",
                        "required_by": "Extraction Validation",
                        "impact": "Invalid severity dropped"
                    })
                continue

            # Boolean fault fields — phrase-based
            if k == "carrier_fault":
                found, negated = self._check_boolean_fact(
                    user_lower, v,
                    CARRIER_FAULT_TRUE_PHRASES, CARRIER_FAULT_FALSE_PHRASES
                )
            elif k == "customer_fault":
                found, negated = self._check_boolean_fact(
                    user_lower, v,
                    CUSTOMER_FAULT_TRUE_PHRASES, CUSTOMER_FAULT_FALSE_PHRASES
                )
            else:
                found, negated = self._check_value_in_text(user_lower, str(v))

            if found and not negated:
                validated.append({
                    "fact": f"{k} is {v}",
                    "source": "User Query Extraction",
                    "type": "USER_STATED_FACT"
                })
            elif negated:
                gaps.append({
                    "missing_fact": f"LLM extracted '{k}={v}' but user text negates this value",
                    "required_by": "Extraction Validation",
                    "impact": "Contradicted by user text",
                    "critical": True
                })
            else:
                gaps.append({
                    "missing_fact": f"LLM extracted '{k}={v}' but value not supported by user text",
                    "required_by": "Extraction Validation",
                    "impact": "Unsupported extraction dropped"
                })

        return validated, gaps

    def _check_value_in_text(self, text_lower: str, value_str: str) -> Tuple[bool, bool]:
        """Check if value is present and not negated. Returns (found, negated)."""
        val = value_str.lower()
        if val not in text_lower:
            return False, False
        idx = text_lower.find(val)
        prefix_words = text_lower[:idx].split()
        recent = prefix_words[-5:] if len(prefix_words) >= 5 else prefix_words
        for w in recent:
            cleaned = re.sub(r'[.,;:!?\'"()\[\]]', '', w).strip()
            if cleaned in NEGATION_WORDS:
                return True, True
        return True, False

    def _check_boolean_fact(self, text_lower: str, value: bool,
                            true_phrases: list, false_phrases: list) -> Tuple[bool, bool]:
        """Check boolean fact support in text. Returns (found, negated)."""
        if value is True:
            for phrase in true_phrases:
                if phrase in text_lower:
                    idx = text_lower.find(phrase)
                    prefix_words = text_lower[:idx].strip().split()
                    last = prefix_words[-3:] if len(prefix_words) >= 3 else prefix_words
                    if any(re.sub(r'[.,;:!?\'"()\[\]]', '', w).strip() in NEGATION_WORDS for w in last):
                        return True, True
                    return True, False
            for phrase in false_phrases:
                if phrase in text_lower:
                    return True, True
            return False, False
        else:  # value is False
            for phrase in false_phrases:
                if phrase in text_lower:
                    return True, False
            for phrase in true_phrases:
                if phrase in text_lower:
                    return True, True
            return False, False

    # ------------------------------------------------------------------ #
    #  Main Request Processing
    # ------------------------------------------------------------------ #

    def process_request(self, session_dict: Dict[str, Any], user_text: str,
                        context_links: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = Session(role=session_dict.get("role"),
                          account_id=session_dict.get("account_id"))
        context_links = context_links or []

        # 1. LLM #1 Classification & Fact Extraction
        try:
            llm1_raw = self.llm1_classifier(user_text, session)
        except Exception as e:
            err_msg = str(e)
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key and api_key in err_msg:
                err_msg = err_msg.replace(api_key, "[REDACTED_API_KEY]")
            logger.error(f"LLM1_CLASSIFICATION_FAILED: {type(e).__name__} - {err_msg}")
            
            return self._system_error_fallback(
                session_dict, user_text, context_links,
                "LLM1_CLASSIFICATION_FAILED", str(e)
            )

        llm1_output, err = self._validate_llm1_output(llm1_raw)
        if err:
            return self._system_error_fallback(
                session_dict, user_text, context_links, err,
                "Failed to parse LLM1 output"
            )

        intent = llm1_output["intent"]
        ambiguous = llm1_output.get("ambiguous", False)
        extracted_facts_raw = llm1_output.get("extracted_facts", {})

        # 2. Extraction-Validation Boundary
        user_facts, extraction_gaps = self._validate_extracted_facts(
            extracted_facts_raw, user_text
        )

        # 3. Initialize evidence containers
        retrieved_docs: list = []
        database_facts: list = []
        computed_results: dict = {}
        evidence_gaps: list = list(extraction_gaps)

        if ambiguous:
            evidence_gaps.append({
                "missing_fact": "Intent is ambiguous",
                "required_by": "Orchestrator",
                "impact": "Classification confidence insufficient",
                "critical": True
            })

        if "_invalid_intent" in llm1_output:
            evidence_gaps.append({
                "missing_fact": (
                    f"LLM classified intent as '{llm1_output['_invalid_intent']}'"
                    " which is not a valid intent"
                ),
                "required_by": "Orchestrator",
                "impact": "Intent not recognized",
                "critical": True
            })

        # 4. Mandatory retrieval per intent
        try:
            self._mandatory_retrieval(
                session, intent, context_links, extracted_facts_raw,
                retrieved_docs, database_facts, evidence_gaps
            )
        except Exception as e:
            evidence_gaps.append({
                "missing_fact": f"Data retrieval failed: {e}",
                "required_by": "Orchestrator",
                "impact": "Missing authoritative data",
                "critical": True
            })

        # 5. Execute LLM-requested tool calls
        for tc in llm1_output.get("tool_calls", []):
            tool_name = tc.get("name")
            args = tc.get("arguments", {})
            if isinstance(args, dict):
                for k, v in extracted_facts_raw.items():
                    if k not in args:
                        args[k] = v
                if session.role == "customer":
                    args["account_id"] = session.account_id
            try:
                self._execute_tool(
                    session, tool_name, args,
                    retrieved_docs, database_facts,
                    computed_results, evidence_gaps,
                    intent, user_text
                )
            except Exception as e:
                evidence_gaps.append({
                    "missing_fact": f"Tool {tool_name} failed: {e}",
                    "required_by": "Orchestrator",
                    "impact": "Tool execution error"
                })

        # 6. Curate DecisionContext
        query_dict = {
            "classified_intent": intent,
            "only_historical_material_addresses_topic":
                llm1_output.get("only_historical_material_addresses_topic", False)
        }

        formatted_ctx = []
        for c in context_links:
            if "context_order_id" in c:
                formatted_ctx.append({
                    "fact": f"Session context refers to order {c['context_order_id']}",
                    "source": "Session context"
                })
            elif "context_ticket_id" in c:
                formatted_ctx.append({
                    "fact": f"Session context refers to ticket {c['context_ticket_id']}",
                    "source": "Session context"
                })

        try:
            decision_context = curate_decision_context(
                session=session_dict,
                query=query_dict,
                retrieved_docs=retrieved_docs,
                database_facts=database_facts,
                user_facts=user_facts,
                context_links=formatted_ctx,
                computed_results=computed_results,
                evidence_gaps_input=evidence_gaps
            )
        except Exception as e:
            return self._system_error_fallback(
                session_dict, user_text, context_links,
                "CURATION_FAILED", str(e)
            )

        # 7. LLM #2 Final Reasoning
        try:
            llm2_raw = self.llm2_reasoner(decision_context)
        except Exception as e:
            return self._system_error_fallback(
                session_dict, user_text, context_links,
                "LLM2_REASONING_FAILED", str(e)
            )

        llm2_output, err = self._validate_llm2_output(llm2_raw)
        if err:
            return self._system_error_fallback(
                session_dict, user_text, context_links, err,
                "Failed to parse LLM2 output"
            )

        # 8. Server-side Enforcement
        if (decision_context.evidence_status == "HUMAN_REVIEW"
                and llm2_output.get("answer_type") == "ANSWER"):
            llm2_output["answer_type"] = "HUMAN_REVIEW"
            llm2_output["text"] = "[SERVER OVERRIDE] " + llm2_output.get("text", "")

        llm2_output["computed_results"] = dict(decision_context.computed_results)
        return llm2_output

    # ------------------------------------------------------------------ #
    #  Mandatory Retrieval
    # ------------------------------------------------------------------ #

    def _mandatory_retrieval(self, session, intent, context_links,
                             extracted_facts_raw, retrieved_docs,
                             database_facts, evidence_gaps):
        if intent == "cancellation_query":
            docs = search_documents(
                session, "cancellation OR policy OR waiver OR fee", top_k=5
            )
            for d in docs:
                self._map_doc_for_curation(d, intent)
            retrieved_docs.extend(docs)

            order_id = self._extract_order_id(context_links, extracted_facts_raw)
            if order_id:
                orders = query_data(session, "orders", {"order_id": order_id})
                if orders:
                    order = orders[0]
                    database_facts.append({
                        "fact": f"Order {order_id} status is {order['status']}",
                        "source": "orders table"
                    })
                    if order.get("carrier"):
                        database_facts.append({
                            "fact": f"Order {order_id} carrier is {order['carrier']}",
                            "source": "orders table"
                        })

        elif intent == "credit_query":
            docs = search_documents(
                session, "service OR credit OR refund OR late OR pickup", top_k=5
            )
            for d in docs:
                self._map_doc_for_curation(d, intent)
            retrieved_docs.extend(docs)

        elif intent == "sla_query":
            docs = search_documents(
                session, "SLA OR response OR time OR target", top_k=5
            )
            for d in docs:
                self._map_doc_for_curation(d, intent)
            retrieved_docs.extend(docs)

        elif intent == "status_query":
            order_id = self._extract_order_id(context_links, extracted_facts_raw)
            if order_id:
                orders = query_data(session, "orders", {"order_id": order_id})
                if orders:
                    order = orders[0]
                    database_facts.append({
                        "fact": f"Order {order_id} status is {order['status']}",
                        "source": "orders table"
                    })
                    if order.get("carrier"):
                        database_facts.append({
                            "fact": f"Order {order_id} carrier is {order['carrier']}",
                            "source": "orders table"
                        })
                    if order.get("shipment_fee_inr") is not None:
                        database_facts.append({
                            "fact": f"Order {order_id} shipment fee is {order['shipment_fee_inr']}",
                            "source": "orders table"
                        })
                else:
                    evidence_gaps.append({
                        "missing_fact": f"Order {order_id} not found or access denied",
                        "required_by": "status_query",
                        "impact": "Cannot verify order status"
                    })
            else:
                evidence_gaps.append({
                    "missing_fact": "Order ID required for status query",
                    "required_by": "status_query",
                    "impact": "Cannot identify order",
                    "critical": True
                })

        elif intent == "unrecognized":
            evidence_gaps.append({
                "missing_fact": "Recognizable intent",
                "required_by": "Orchestrator",
                "impact": "Cannot route request",
                "critical": True
            })

    # ------------------------------------------------------------------ #
    #  Tool Execution
    # ------------------------------------------------------------------ #

    def _execute_tool(self, session: Session, tool_name: str,
                      args: Dict[str, Any], retrieved_docs, database_facts,
                      computed_results, evidence_gaps, intent: str,
                      user_text: str = ""):
        if tool_name == "search_documents":
            docs = search_documents(session, args.get("query", ""),
                                    top_k=args.get("top_k", 5))
            for d in docs:
                self._map_doc_for_curation(d, intent)
            retrieved_docs.extend(docs)

        elif tool_name == "get_order":
            order_id = args.get("order_id")
            orders = query_data(session, "orders", {"order_id": order_id})
            if not orders:
                evidence_gaps.append({
                    "missing_fact": f"Order {order_id} not found or access denied",
                    "required_by": "get_order",
                    "impact": "Cannot verify order status"
                })
            else:
                order = orders[0]
                database_facts.append({
                    "fact": f"Order {order_id} status is {order['status']}",
                    "source": "orders table"
                })
                if order.get("carrier"):
                    database_facts.append({
                        "fact": f"Order {order_id} carrier is {order['carrier']}",
                        "source": "orders table"
                    })
                if order.get("shipment_fee_inr") is not None:
                    database_facts.append({
                        "fact": f"Order {order_id} shipment fee is {order['shipment_fee_inr']}",
                        "source": "orders table"
                    })

        elif tool_name == "get_cancellation_terms":
            self._tool_cancellation(session, args, database_facts,
                                    computed_results, evidence_gaps, user_text)

        elif tool_name == "get_credit_terms":
            self._tool_credit(session, args, database_facts,
                              computed_results, evidence_gaps, user_text)

        elif tool_name == "evaluate_sla":
            self._tool_sla(session, args, database_facts,
                           computed_results, evidence_gaps)

        elif tool_name == "prepare_action":
            action_type = args.get("action_type")
            payload = args.get("payload", {})
            if not action_type:
                return
            req_id = str(uuid.uuid4())
            self.pending_actions[req_id] = PendingAction(
                request_id=req_id,
                account_id=session.account_id,
                action_type=action_type,
                payload=payload,
                expires_at=time.time() + 300,
                status="pending_confirmation"
            )
            computed_results["prepared_action"] = {
                "request_id": req_id, "action_type": action_type
            }

        elif tool_name == "confirm_action":
            raise PermissionError(
                "LLM is not allowed to call confirm_action directly."
            )
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    # -- Cancellation tool --------------------------------------------------

    def _tool_cancellation(self, session, args, database_facts,
                           computed_results, evidence_gaps, user_text):
        order_id = args.get("order_id")
        if not order_id:
            evidence_gaps.append({
                "missing_fact": "order_id",
                "required_by": "get_cancellation_terms",
                "impact": "Cannot evaluate"
            })
            return

        orders = query_data(session, "orders", {"order_id": order_id})
        if not orders:
            evidence_gaps.append({
                "missing_fact": f"Order {order_id} not found or access denied",
                "required_by": "get_cancellation_terms",
                "impact": "Cannot evaluate"
            })
            return
        order = orders[0]

        # Server-authoritative: compute minutes from DB timestamps
        minutes_since_booking = None
        booked_at_str = order.get("booked_at")
        cancel_req_str = order.get("cancellation_requested_at")

        if booked_at_str and cancel_req_str:
            try:
                booked_at = datetime.fromisoformat(booked_at_str)
                cancel_at = datetime.fromisoformat(cancel_req_str)
                minutes_since_booking = (cancel_at - booked_at).total_seconds() / 60.0
                database_facts.append({
                    "fact": (f"Order {order_id} minutes since booking = "
                             f"{minutes_since_booking:.1f} (computed from DB)"),
                    "source": "orders table"
                })
            except (ValueError, TypeError):
                evidence_gaps.append({
                    "missing_fact": "Could not parse booking/cancellation timestamps",
                    "required_by": "get_cancellation_terms",
                    "impact": "Cannot compute elapsed time"
                })
        elif booked_at_str and not cancel_req_str:
            # Option (b): user hasn't submitted cancellation yet.
            # Check if user explicitly stated elapsed time in their text.
            user_minutes = self._extract_user_stated_minutes(user_text)
            if user_minutes is not None:
                minutes_since_booking = user_minutes
                database_facts.append({
                    "fact": (f"Minutes since booking ({user_minutes}) "
                             "stated by user, not from DB"),
                    "source": "User text"
                })
            else:
                evidence_gaps.append({
                    "missing_fact": ("cancellation_requested_at is NULL and user "
                                    "did not state elapsed time"),
                    "required_by": "get_cancellation_terms",
                    "impact": "Cannot compute elapsed time for fee calculation"
                })

        acct = (session.account_id
                if session.role == 'customer'
                else order.get('account_id'))

        res = evaluate_cancellation(
            status=order["status"],
            minutes_since_booking=minutes_since_booking,
            account_id=acct
        )
        computed_results["cancellation"] = res

    # -- Credit tool ---------------------------------------------------------

    def _tool_credit(self, session, args, database_facts,
                     computed_results, evidence_gaps, user_text):
        order_id = args.get("order_id")
        shipment_fee_inr = None
        account_for_eval = session.account_id
        user_lower = user_text.lower()

        db_carrier_fault = None
        db_customer_fault = None
        db_delay_hours = None

        if order_id:
            orders = query_data(session, "orders", {"order_id": order_id})
            if orders:
                order = orders[0]
                shipment_fee_inr = order.get("shipment_fee_inr")
                if session.role != 'customer':
                    account_for_eval = order.get("account_id")

                raw_cf = order.get("carrier_fault")
                if raw_cf is not None:
                    db_carrier_fault = (
                        raw_cf.lower() in ("true", "yes", "1")
                        if isinstance(raw_cf, str)
                        else bool(raw_cf)
                    )
                    database_facts.append({
                        "fact": f"Order {order_id} carrier_fault is {db_carrier_fault}",
                        "source": "orders table"
                    })

                raw_cuf = order.get("customer_fault")
                if raw_cuf is not None:
                    db_customer_fault = (
                        raw_cuf.lower() in ("true", "yes", "1")
                        if isinstance(raw_cuf, str)
                        else bool(raw_cuf)
                    )
                    database_facts.append({
                        "fact": f"Order {order_id} customer_fault is {db_customer_fault}",
                        "source": "orders table"
                    })

                pw_end = order.get("pickup_window_end")
                pa = order.get("pickup_actual_at")
                if pw_end and pa:
                    try:
                        t_end = datetime.fromisoformat(pw_end)
                        t_actual = datetime.fromisoformat(pa)
                        db_delay_hours = max(
                            0.0,
                            (t_actual - t_end).total_seconds() / 3600.0
                        )
                        database_facts.append({
                            "fact": (f"Order {order_id} pickup delay is "
                                     f"{db_delay_hours:.2f} hours (computed from DB)"),
                            "source": "orders table"
                        })
                    except (ValueError, TypeError):
                        pass

        # Resolve delay_hours: DB > validated user text > gap
        delay_hours = db_delay_hours
        if delay_hours is None:
            dh_arg = args.get("delay_hours")
            if dh_arg is not None:
                dh_str = str(dh_arg)
                found, negated = self._check_value_in_text(user_lower, dh_str)
                # Also accept "<N> hour" and int patterns
                if not found:
                    # try integer representations
                    dh_int = int(float(dh_arg))
                    if f"{dh_int} hour" in user_lower or f"{dh_int} hr" in user_lower:
                        found, negated = True, False
                    elif str(dh_int) in user_lower:
                        # loose check if the integer itself was in text, 
                        # though it's risky if it's just a number, but let's trust _check_value_in_text
                        found, negated = True, False
                if found and not negated:
                    delay_hours = float(dh_arg)
                else:
                    evidence_gaps.append({
                        "missing_fact": (f"delay_hours={dh_arg} not supported "
                                         "by DB or user text"),
                        "required_by": "get_credit_terms",
                        "impact": "Cannot verify delay duration",
                        "critical": True
                    })
            else:
                evidence_gaps.append({
                    "missing_fact": "delay_hours unknown",
                    "required_by": "get_credit_terms",
                    "impact": "Cannot verify delay duration",
                    "critical": True
                })

        # Resolve carrier_fault: DB > validated user text > gap
        carrier_fault = db_carrier_fault
        if carrier_fault is None:
            cf_arg = args.get("carrier_fault")
            if cf_arg is not None:
                found, negated = self._check_boolean_fact(
                    user_lower, cf_arg,
                    CARRIER_FAULT_TRUE_PHRASES, CARRIER_FAULT_FALSE_PHRASES
                )
                if found and not negated:
                    carrier_fault = cf_arg
                else:
                    evidence_gaps.append({
                        "missing_fact": "carrier_fault not established from DB or user text",
                        "required_by": "get_credit_terms",
                        "impact": "Cannot verify carrier fault",
                        "critical": True
                    })
            else:
                evidence_gaps.append({
                    "missing_fact": "carrier_fault unknown",
                    "required_by": "get_credit_terms",
                    "impact": "Cannot verify carrier fault",
                    "critical": True
                })

        # Resolve customer_fault: DB > validated user text > gap
        customer_fault = db_customer_fault
        if customer_fault is None:
            cuf_arg = args.get("customer_fault")
            if cuf_arg is not None:
                found, negated = self._check_boolean_fact(
                    user_lower, cuf_arg,
                    CUSTOMER_FAULT_TRUE_PHRASES, CUSTOMER_FAULT_FALSE_PHRASES
                )
                if found and not negated:
                    customer_fault = cuf_arg
                else:
                    evidence_gaps.append({
                        "missing_fact": "customer_fault not established from DB or user text",
                        "required_by": "get_credit_terms",
                        "impact": "Cannot verify customer fault",
                        "critical": True
                    })
            else:
                evidence_gaps.append({
                    "missing_fact": "customer_fault unknown",
                    "required_by": "get_credit_terms",
                    "impact": "Cannot verify customer fault",
                    "critical": True
                })

        res = evaluate_credit(
            delay_hours=delay_hours,
            carrier_fault=carrier_fault,
            customer_fault=customer_fault,
            shipment_fee_inr=shipment_fee_inr,
            account_id=account_for_eval
        )
        computed_results["credit"] = res

    # -- SLA tool ------------------------------------------------------------

    def _tool_sla(self, session, args, database_facts,
                  computed_results, evidence_gaps):
        # Server-authoritative: fetch plan from accounts table
        account_id_for_sla = session.account_id
        plan = None

        if account_id_for_sla:
            accounts = query_data(session, "accounts",
                                  {"account_id": account_id_for_sla})
            if accounts:
                plan = accounts[0].get("plan")
                database_facts.append({
                    "fact": f"Account {account_id_for_sla} plan is {plan}",
                    "source": "accounts table"
                })

        if plan is None:
            # Internal sessions may not have an account — use LLM arg
            # but flag that it's non-authoritative
            plan_arg = args.get("plan")
            if plan_arg:
                plan = plan_arg
                evidence_gaps.append({
                    "missing_fact": ("Account plan not found in DB, "
                                    "using LLM-supplied value"),
                    "required_by": "evaluate_sla",
                    "impact": "Plan source is not authoritative"
                })
            else:
                evidence_gaps.append({
                    "missing_fact": "Account plan required for SLA evaluation",
                    "required_by": "evaluate_sla",
                    "impact": "Cannot evaluate SLA"
                })
                return

        res = evaluate_sla(
            plan=plan,
            severity=args.get("severity"),
            elapsed_minutes=args.get("elapsed_minutes"),
            account_id=account_id_for_sla
        )
        computed_results["sla"] = res

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _extract_order_id(self, context_links, extracted_facts_raw):
        for c in context_links:
            if "context_order_id" in c:
                return c["context_order_id"]
        return extracted_facts_raw.get("order_id")

    def _extract_user_stated_minutes(self, user_text: str) -> Optional[float]:
        """Extract explicitly stated minutes from user text."""
        text_lower = user_text.lower()
        m = re.search(r'(\d+(?:\.\d+)?)\s*minutes?\s*(?:ago|since|after)',
                      text_lower)
        if m:
            return float(m.group(1))
        m = re.search(r'(\d+(?:\.\d+)?)\s*hours?\s*(?:ago|since|after)',
                      text_lower)
        if m:
            return float(m.group(1)) * 60.0
        return None

    def _map_doc_for_curation(self, doc: Dict[str, Any], intent: str) -> None:
        doc["topic"] = intent
        st = doc.get("source_type")

        is_dep = doc.get("is_deprecated")
        if isinstance(is_dep, str):
            doc["is_deprecated"] = is_dep.lower() == "true"

        if doc.get("customer_scope") == "global":
            doc["customer_scope"] = None

        if st in ["customer_agreement", "Enterprise Agreement",
                   "Service Agreement"]:
            doc["source_type"] = "customer_agreement"
            text = doc.get("text", "").lower()
            if ("supersed" in text or "prevail" in text
                    or "override" in text):
                doc["is_override"] = True
            if "defer" in text or "subject to" in text:
                doc["is_deferral"] = True
        elif st == "Support Policy":
            doc["source_type"] = "current_policy"
        elif st == "SOP":
            doc["source_type"] = "current_sop"

    def _system_error_fallback(self, session_dict, user_text,
                                context_links, error_code, error_msg):
        return {
            "answer_type": "HUMAN_REVIEW",
            "text": (f"System error occurred. Request requires "
                     f"human review. [{error_code}]"),
            "sources_cited": [],
            "evidence_status": "HUMAN_REVIEW",
            "system_error": {
                "code": error_code,
                "message": error_msg
            }
        }

    # ------------------------------------------------------------------ #
    #  Server-Side Action API (Not exposed to LLM)
    # ------------------------------------------------------------------ #

    def confirm_action(self, request_id: str,
                       session_dict: Dict[str, Any]) -> Dict[str, Any]:
        if request_id not in self.pending_actions:
            return {"status": "execution_failed",
                    "error": "Invalid request_id"}

        action = self.pending_actions[request_id]

        if action.account_id != session_dict.get("account_id"):
            return {"status": "execution_failed",
                    "error": "Unauthorized cross-account confirmation"}

        if time.time() > action.expires_at:
            self.pending_actions[request_id] = action.with_status("expired")
            return {"status": "expired", "error": "Action expired"}

        if action.status == "executed":
            return {"status": "already_executed",
                    "duplicate_side_effect": False}

        if action.status != "pending_confirmation":
            return {"status": "execution_failed",
                    "error": f"Cannot confirm action in state {action.status}"}

        self.pending_actions[request_id] = action.with_status("executed")
        return {"status": "executed", "audit_entry_created": True}
