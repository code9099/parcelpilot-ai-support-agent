from typing import Dict, Any, Optional, List
from .models import ACCOUNT_TERMS, AppliedRule

def evaluate_credit(delay_hours: Optional[float], carrier_fault: Optional[bool], customer_fault: Optional[bool], shipment_fee_inr: Optional[float], account_id: Optional[str]) -> Dict[str, Any]:
    """
    Evaluates service credit eligibility and amount.
    Returns dict with: eligible, credit_amount_inr, manager_approval_required, reasoning, applied_rules.
    """
    applied_rules: List[AppliedRule] = []

    # 1. Missing Facts check (SOP v4 §3)
    if delay_hours is None or carrier_fault is None or customer_fault is None:
        applied_rules.append(AppliedRule(
            rule_id="credit_missing_facts_uncertainty",
            source_file="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
            source_section="§3",
            source_type="current_sop",
            precedence_note="Uncertainty prohibition rule applies."
        ))
        return {
            "eligible": None,
            "credit_amount_inr": None,
            "manager_approval_required": None,
            "reasoning": "Missing required facts (delay, carrier fault, or customer fault). Do not promise credit when unknown.",
            "applied_rules": [r.to_dict() for r in applied_rules]
        }

    # 2. Extract account terms
    threshold_hours = 2.0
    credit_amount_fixed = None
    
    if account_id and account_id in ACCOUNT_TERMS:
        terms = ACCOUNT_TERMS[account_id]
        
        # Check LumenWorks override
        if terms.get("credit_threshold_hours") is not None:
            threshold_hours = terms["credit_threshold_hours"]
            applied_rules.append(AppliedRule(
                rule_id="credit_lumenworks_threshold_override",
                source_file="06_LumenWorks_Service_Agreement.pdf",
                source_section="§3",
                source_type="customer_agreement",
                precedence_note=f"Overrides default threshold to {threshold_hours} hours."
            ))
            
        if terms.get("credit_amount_fixed") is not None:
            credit_amount_fixed = terms["credit_amount_fixed"]
            applied_rules.append(AppliedRule(
                rule_id="credit_lumenworks_amount_override",
                source_file="06_LumenWorks_Service_Agreement.pdf",
                source_section="§3",
                source_type="customer_agreement",
                precedence_note=f"Overrides default credit calculation to fixed ₹{credit_amount_fixed}."
            ))

        if terms.get("credit_monthly_cap") is not None:
            applied_rules.append(AppliedRule(
                rule_id="credit_northstar_monthly_cap",
                source_file="05_Northstar_Logistics_Enterprise_Agreement.pdf",
                source_section="§3",
                source_type="customer_agreement",
                precedence_note=f"Monthly aggregate service credits are capped at INR {terms['credit_monthly_cap']}. Unless this agreement states otherwise, the current ParcelPilot service-credit SOP applies."
            ))

    # 3. Determine Eligibility
    if delay_hours > threshold_hours and carrier_fault and not customer_fault:
        eligible = True
    else:
        eligible = False
        
    if not eligible:
        applied_rules.append(AppliedRule(
            rule_id="credit_eligibility_default",
            source_file="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
            source_section="§2",
            source_type="current_sop",
            precedence_note="Default eligibility criteria not met."
        ))
        return {
            "eligible": False,
            "credit_amount_inr": 0,
            "manager_approval_required": False,
            "reasoning": f"Not eligible. Delay ({delay_hours} hrs) must be > {threshold_hours} hrs, carrier at fault (was {carrier_fault}), customer not at fault (was {customer_fault}).",
            "applied_rules": [r.to_dict() for r in applied_rules]
        }
        
    # 4. Compute Amount
    if credit_amount_fixed is not None:
        amount = float(credit_amount_fixed)
        reasoning = f"Eligible. Fixed amount ₹{amount} applied per agreement."
    else:
        if shipment_fee_inr is None:
            return {
                "eligible": None,
                "credit_amount_inr": None,
                "manager_approval_required": None,
                "reasoning": "Missing shipment_fee_inr required to compute default credit amount.",
                "applied_rules": [r.to_dict() for r in applied_rules]
            }
        # SOP v4 §2 default
        amount = min(500.0, shipment_fee_inr * 0.10)
        reasoning = f"Eligible. Default formula min(500, fee * 0.10) applied: min(500, {shipment_fee_inr} * 0.10) = ₹{amount}."
        
        # Add default SOP rule if not overridden
        if not any(r.rule_id == "credit_lumenworks_amount_override" for r in applied_rules):
             applied_rules.append(AppliedRule(
                rule_id="credit_amount_default",
                source_file="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
                source_section="§2",
                source_type="current_sop",
                precedence_note="Default calculation applied."
            ))

    # 5. Manager Approval Check (SOP v4 §3)
    manager_approval_required = (amount > 1000)
    if manager_approval_required:
        applied_rules.append(AppliedRule(
            rule_id="credit_manager_approval",
            source_file="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
            source_section="§3",
            source_type="current_sop",
            precedence_note="Credits > ₹1000 require manager approval."
        ))
        reasoning += " Manager approval is required."

    return {
        "eligible": True,
        "credit_amount_inr": amount,
        "manager_approval_required": manager_approval_required,
        "reasoning": reasoning,
        "applied_rules": [r.to_dict() for r in applied_rules]
    }
