from typing import Dict, Any, Optional, Tuple, List
from .models import ACCOUNT_TERMS, AppliedRule

def evaluate_cancellation(status: str, minutes_since_booking: Optional[float], account_id: Optional[str]) -> Dict[str, Any]:
    """
    Evaluates cancellation eligibility and fees.
    Returns dict with: eligible, fee_inr, reasoning, applied_rules.
    """
    applied_rules: List[AppliedRule] = []
    
    # 1. Check account overrides
    override = None
    if account_id and account_id in ACCOUNT_TERMS:
        override = ACCOUNT_TERMS[account_id].get("cancellation_override")
        
    if override == "BOOKED_NO_FEE":
        if status == "BOOKED":
            applied_rules.append(AppliedRule(
                rule_id="cancellation_northstar_override",
                source_file="05_Northstar_Logistics_Enterprise_Agreement.pdf",
                source_section="§2",
                source_type="customer_agreement",
                precedence_note="Overrides SOP default fee for BOOKED status"
            ))
            return {
                "eligible": True,
                "fee_inr": 0,
                "reasoning": "Account explicitly waives cancellation fees for any BOOKED shipment before pickup, regardless of time.",
                "applied_rules": [r.to_dict() for r in applied_rules]
            }

    # 2. Add SOP rule to provenance (since we fell through to default logic)
    applied_rules.append(AppliedRule(
        rule_id="cancellation_default",
        source_file="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
        source_section="§1",
        source_type="current_sop",
        precedence_note="SOP defaults apply" if override is None else "Override not applicable to this state"
    ))

    # 3. Default rules (SOP v4 §1)
    if status == "DRAFT":
        return {
            "eligible": True,
            "fee_inr": 0,
            "reasoning": "Order is DRAFT. May be cancelled with no fee.",
            "applied_rules": [r.to_dict() for r in applied_rules]
        }
    elif status == "BOOKED":
        if minutes_since_booking is None:
            return {
                "eligible": None,
                "fee_inr": None,
                "reasoning": "Missing minutes_since_booking required to evaluate BOOKED cancellation fee under defaults.",
                "applied_rules": [r.to_dict() for r in applied_rules]
            }
        
        if minutes_since_booking <= 30.0:
            return {
                "eligible": True,
                "fee_inr": 0,
                "reasoning": "Order is BOOKED and <= 30 minutes since booking. May be cancelled with no fee.",
                "applied_rules": [r.to_dict() for r in applied_rules]
            }
        else:
            return {
                "eligible": True,
                "fee_inr": 250,
                "reasoning": "Order is BOOKED and > 30 minutes since booking. May be cancelled with ₹250 fee.",
                "applied_rules": [r.to_dict() for r in applied_rules]
            }
    elif status == "PICKED_UP":
        return {
            "eligible": False,
            "fee_inr": None,
            "reasoning": "Order is already PICKED_UP. Do not cancel. Use return-to-origin workflow.",
            "applied_rules": [r.to_dict() for r in applied_rules]
        }
    elif status == "DELIVERED":
        return {
            "eligible": False,
            "fee_inr": None,
            "reasoning": "Order is DELIVERED. Cannot be cancelled.",
            "applied_rules": [r.to_dict() for r in applied_rules]
        }
    else:
        return {
            "eligible": None,
            "fee_inr": None,
            "reasoning": f"Unknown order status: {status}.",
            "applied_rules": [r.to_dict() for r in applied_rules]
        }
