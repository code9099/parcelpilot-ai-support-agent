from typing import Dict, Any, Optional, List
from .models import ACCOUNT_TERMS, AppliedRule

# Plan defaults from Support Policy v3 §3
SLA_DEFAULTS = {
    "Enterprise": {
        "P1": {"target": 30, "unit": "minutes", "is_24x7": True},
        "P2": {"target": 2, "unit": "hours", "is_24x7": True},
        "P3": {"target": 1, "unit": "business_days", "is_24x7": False}
    },
    "Growth": {
        "P1": {"target": 2, "unit": "business_hours", "is_24x7": False},
        "P2": {"target": 4, "unit": "business_hours", "is_24x7": False},
        "P3": {"target": 2, "unit": "business_days", "is_24x7": False}
    },
    "Standard": {
        "P1": {"target": 4, "unit": "business_hours", "is_24x7": False},
        "P2": {"target": 1, "unit": "business_days", "is_24x7": False},
        "P3": {"target": 2, "unit": "business_days", "is_24x7": False}
    }
}

def evaluate_sla(plan: str, severity: str, account_id: Optional[str], elapsed_minutes: Optional[float]) -> Dict[str, Any]:
    """
    Evaluates SLA target and breach status.
    Returns dict with: target_string, breach_status, applied_rules.
    """
    applied_rules: List[AppliedRule] = []

    if plan not in SLA_DEFAULTS:
        return {
            "target_string": f"Unknown plan: {plan}",
            "breach_status": "cannot_determine_without_business_hours_calendar",
            "applied_rules": []
        }
    if severity not in ["P1", "P2", "P3"]:
        return {
            "target_string": f"Unknown severity: {severity}",
            "breach_status": "cannot_determine_without_business_hours_calendar",
            "applied_rules": []
        }

    # Base target
    target_obj = SLA_DEFAULTS[plan][severity]
    source_desc = f"Support Policy v3 §3 ({plan} default)"
    
    # Check overrides
    if account_id and account_id in ACCOUNT_TERMS:
        terms = ACCOUNT_TERMS[account_id]
        if terms.get("sla_overrides") and severity in terms["sla_overrides"]:
            target_obj = terms["sla_overrides"][severity]
            source_desc = "Customer Agreement override"
            applied_rules.append(AppliedRule(
                rule_id="sla_northstar_override",
                source_file="05_Northstar_Logistics_Enterprise_Agreement.pdf",
                source_section="§1",
                source_type="customer_agreement",
                precedence_note="Replaces ParcelPilot's standard support-policy targets."
            ))
        
        if terms.get("sla_coverage_restriction") is not None:
             applied_rules.append(AppliedRule(
                rule_id="sla_lumenworks_restriction",
                source_file="06_LumenWorks_Service_Agreement.pdf",
                source_section="§1",
                source_type="customer_agreement",
                precedence_note="No weekend or after-hours support coverage restriction applies."
            ))

    # Add default if not overridden
    if not any(r.rule_id == "sla_northstar_override" for r in applied_rules):
        applied_rules.append(AppliedRule(
            rule_id="sla_default",
            source_file="01_Support_Policy_v3_CURRENT.pdf",
            source_section="§3",
            source_type="current_policy",
            precedence_note="SOP default applies."
        ))

    # Format target string
    target_val = target_obj["target"]
    unit = target_obj["unit"].replace('_', ' ')
    time_scope = ", 24x7" if target_obj["is_24x7"] else ""
    target_string = f"{target_val} {unit}{time_scope}"

    # Calculate breach
    breach_status = "cannot_determine_without_business_hours_calendar"
    if target_obj["is_24x7"] and elapsed_minutes is not None:
        # Convert target to minutes
        target_mins = 0
        if "minutes" in target_obj["unit"]:
            target_mins = target_val
        elif "hours" in target_obj["unit"]:
            target_mins = target_val * 60
        elif "days" in target_obj["unit"]:
            target_mins = target_val * 24 * 60
            
        if elapsed_minutes > target_mins:
            breach_status = "breached"
        else:
            breach_status = "not_breached"
            
    return {
        "target_string": target_string,
        "breach_status": breach_status,
        "applied_rules": [r.to_dict() for r in applied_rules]
    }
