from typing import Dict, Any, Optional

ACCOUNT_TERMS = {
    "ACCT-001": { # Northstar
        "cancellation_override": "BOOKED_NO_FEE", 
        "credit_threshold_hours": None,
        "credit_amount_fixed": None,
        "credit_monthly_cap": 5000,
        "sla_overrides": {
            "P1": {"target": 15, "unit": "minutes", "is_24x7": True},
            "P2": {"target": 1, "unit": "hours", "is_24x7": True},
            "P3": {"target": 8, "unit": "business_hours", "is_24x7": False}
        },
        "sla_coverage_restriction": None
    },
    "ACCT-002": { # LumenWorks
        "cancellation_override": None, 
        "credit_threshold_hours": 4,
        "credit_amount_fixed": 300,
        "credit_monthly_cap": None,
        "sla_overrides": None,
        "sla_coverage_restriction": "No weekend or after-hours support coverage"
    }
}

class AppliedRule:
    def __init__(self, rule_id: str, source_file: str, source_section: str, source_type: str, precedence_note: Optional[str] = None):
        self.rule_id = rule_id
        self.source_file = source_file
        self.source_section = source_section
        self.source_type = source_type
        self.precedence_note = precedence_note

    def to_dict(self):
        return {
            "rule_id": self.rule_id,
            "source_file": self.source_file,
            "source_section": self.source_section,
            "source_type": self.source_type,
            "precedence_note": self.precedence_note
        }
