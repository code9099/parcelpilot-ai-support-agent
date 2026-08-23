import dataclasses
from types import MappingProxyType
from typing import Any, Mapping, Tuple, List, Optional, Dict

@dataclasses.dataclass(frozen=True)
class Fact:
    fact: str
    type: str
    source: str
    authoritative: bool
    scope: Optional[str]

@dataclasses.dataclass(frozen=True)
class Rule:
    rule_id: str
    source_file: str
    source_section: str
    source_type: str
    is_deprecated: bool
    customer_scope: Optional[str]
    rule_text: str
    applies_to_this_query: bool
    precedence_note: Optional[str]

@dataclasses.dataclass(frozen=True)
class Gap:
    missing_fact: str
    required_by: str
    impact: str

@dataclasses.dataclass(frozen=True)
class ContextItem:
    fact: str
    type: str
    source: str
    warning: str
    authoritative: bool = dataclasses.field(init=False, default=False)

@dataclasses.dataclass(frozen=True)
class DecisionContext:
    session: Mapping[str, Any]
    query: Mapping[str, Any]
    applicable_facts: Tuple[Fact, ...]
    applicable_rules: Tuple[Rule, ...]
    evidence_gaps: Tuple[Gap, ...]
    computed_results: Mapping[str, Any]
    context_only: Tuple[ContextItem, ...]
    evidence_status: str

    def __post_init__(self):
        # Enforce deep immutability
        object.__setattr__(self, 'session', MappingProxyType(dict(self.session)))
        object.__setattr__(self, 'query', MappingProxyType(dict(self.query)))
        object.__setattr__(self, 'computed_results', MappingProxyType(dict(self.computed_results)))
        object.__setattr__(self, 'applicable_facts', tuple(self.applicable_facts))
        object.__setattr__(self, 'applicable_rules', tuple(self.applicable_rules))
        object.__setattr__(self, 'evidence_gaps', tuple(self.evidence_gaps))
        object.__setattr__(self, 'context_only', tuple(self.context_only))


def curate_decision_context(
    session: Dict[str, Any],
    query: Dict[str, Any],
    retrieved_docs: List[Dict[str, Any]],
    database_facts: List[Dict[str, Any]],
    user_facts: List[Dict[str, Any]],
    context_links: List[Dict[str, Any]],
    computed_results: Dict[str, Any],
    evidence_gaps_input: List[Dict[str, Any]] = None
) -> DecisionContext:
    """
    Curates raw inputs into an immutable DecisionContext for the LLM reasoning layer.
    """
    account_id = session.get("account_id")
    topic = query.get("classified_intent")
    
    applicable_rules_list = []
    context_only_list = []
    gaps_list = []
    has_critical_gap = False
    
    # 1. Filter out documents with mismatching customer scope
    valid_docs = []
    for doc in retrieved_docs:
        scope = doc.get("customer_scope")
        if scope and scope != account_id:
            continue
        valid_docs.append(doc)
        
    agreements_on_topic = []
    globals_on_topic = []
    deprecated_on_topic = []
    
    for doc in valid_docs:
        doc_topic = doc.get("topic")
        is_override = doc.get("is_override", False)
        is_deferral = doc.get("is_deferral", False)
        is_deprecated = doc.get("is_deprecated", False)
        
        # Capture supersession relationships
        supersession_note = doc.get("supersession_note", "")
        
        if is_deprecated:
            deprecated_on_topic.append(doc)
            warning_msg = "Deprecated policy."
            if supersession_note:
                warning_msg += f" {supersession_note}"
            context_only_list.append(ContextItem(
                fact=doc.get("text", ""),
                type="DOCUMENT_FACT",
                source=f"{doc.get('source_file')} - {doc.get('source_section')}",
                warning=warning_msg
            ))
            continue
            
        # Non-deprecated docs
        if doc.get("source_type") == "customer_agreement":
            if doc_topic == topic:
                agreements_on_topic.append(doc)
            else:
                context_only_list.append(ContextItem(
                    fact=doc.get("text", ""),
                    type="DOCUMENT_FACT",
                    source=f"{doc.get('source_file')} - {doc.get('source_section')}",
                    warning="Agreement clause not applicable to current query topic."
                ))
        elif doc.get("source_type") in ["current_policy", "current_sop"]:
            if doc_topic == topic:
                globals_on_topic.append(doc)
            else:
                # Add to context only as it might be marginally useful but not governing
                context_only_list.append(ContextItem(
                    fact=doc.get("text", ""),
                    type="DOCUMENT_FACT",
                    source=f"{doc.get('source_file')} - {doc.get('source_section')}",
                    warning="Policy not explicitly applicable to query topic."
                ))
        else:
            # e.g. product_ops_guide, tickets
            context_only_list.append(ContextItem(
                fact=doc.get("text", ""),
                type="DOCUMENT_FACT",
                source=f"{doc.get('source_file')} - {doc.get('source_section')}",
                warning="Supplementary context."
            ))
            
    # Resolve Precedence (Topic-Scoped)
    governing_rules = []
    conflicts = False
    
    if agreements_on_topic:
        overrides = [a for a in agreements_on_topic if a.get("is_override")]
        deferrals = [a for a in agreements_on_topic if a.get("is_deferral")]
        
        if overrides:
            if len(overrides) > 1 and any(o.get("conflicts_with") for o in overrides):
                conflicts = True
            else:
                governing_rules.extend(overrides)
        elif deferrals:
            # Defer to global policy
            if len(globals_on_topic) > 1 and any(g.get("conflicts_with") for g in globals_on_topic):
                conflicts = True
            else:
                governing_rules.extend(globals_on_topic)
                # Also include the deferral clause as a rule setting precedence
                for d in deferrals:
                    d["precedence_note"] = "Defers to global policy."
                    governing_rules.append(d)
        else:
            # If there's an agreement chunk on topic but it doesn't explicitly override or defer? 
            # Silence is not an override. We use global policy.
            if len(globals_on_topic) > 1 and any(g.get("conflicts_with") for g in globals_on_topic):
                conflicts = True
            else:
                governing_rules.extend(globals_on_topic)
    else:
        # Silence (no agreement clause on topic) -> global policy applies
        if len(globals_on_topic) > 1 and any(g.get("conflicts_with") for g in globals_on_topic):
            conflicts = True
        else:
            governing_rules.extend(globals_on_topic)
            
    # Create Rules
    for doc in governing_rules:
        applicable_rules_list.append(Rule(
            rule_id=doc.get("chunk_id", ""),
            source_file=doc.get("source_file", ""),
            source_section=doc.get("source_section", ""),
            source_type=doc.get("source_type", ""),
            is_deprecated=False,
            customer_scope=doc.get("customer_scope"),
            rule_text=doc.get("text", ""),
            applies_to_this_query=True,
            precedence_note=doc.get("precedence_note")
        ))
        
    # Facts
    applicable_facts_list = []
    for f in database_facts:
        applicable_facts_list.append(Fact(f["fact"], "DATABASE_FACT", f["source"], True, f.get("scope")))
    for f in user_facts:
        applicable_facts_list.append(Fact(f["fact"], "USER_STATED_FACT", f["source"], False, None))
    for f in context_links:
        applicable_facts_list.append(Fact(f["fact"], "EXPLICIT_CONTEXT_LINK", f["source"], False, None))
        
    # Evidence Gaps
    if evidence_gaps_input:
        for g in evidence_gaps_input:
            gap = Gap(g["missing_fact"], g["required_by"], g["impact"])
            gaps_list.append(gap)
            if g.get("critical", False):
                has_critical_gap = True
                
    # Evidence Status Determination
    if conflicts:
        evidence_status = "HUMAN_REVIEW"
        gaps_list.append(Gap("Authoritative conflict", "Topic Applicability", "Multiple authoritative sources contradict."))
    elif has_critical_gap:
        evidence_status = "HUMAN_REVIEW"
    elif len(applicable_rules_list) >= 2 or (len(applicable_rules_list) == 1 and governing_rules[0].get("is_override")):
        # We classify as HIGH if 2+ authoritative sources agree OR 1 unambiguous agreement clause on-topic.
        # Note: if a rule explicitly overrides, we count it as HIGH per status semantics.
        evidence_status = "HIGH"
    elif len(applicable_rules_list) == 1:
        evidence_status = "MEDIUM"
    else:
        # No applicable rules.
        # Check if we have deprecated on topic.
        only_historical_material_addresses_topic = query.get("only_historical_material_addresses_topic", False)
        
        if len(deprecated_on_topic) > 0 and only_historical_material_addresses_topic:
            evidence_status = "LOW"
        else:
            evidence_status = "HUMAN_REVIEW"
            gaps_list.append(Gap("Insufficient authoritative evidence", "Precedence Engine", "Cannot definitively establish answer."))
            
    return DecisionContext(
        session=session,
        query=query,
        applicable_facts=applicable_facts_list,
        applicable_rules=applicable_rules_list,
        evidence_gaps=gaps_list,
        computed_results=computed_results,
        context_only=context_only_list,
        evidence_status=evidence_status
    )
