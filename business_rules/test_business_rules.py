import pytest
from .cancellation import evaluate_cancellation
from .credit import evaluate_credit
from .sla import evaluate_sla
from .models import ACCOUNT_TERMS

# --- SLA Tests ---

def test_sla_01_synthetic_not_breached():
    res = evaluate_sla(plan="Enterprise", severity="P1", account_id=None, elapsed_minutes=29.0)
    assert res["target_string"] == "30 minutes, 24x7"
    assert res["breach_status"] == "not_breached"
    assert any(r["rule_id"] == "sla_default" for r in res["applied_rules"])

def test_sla_02_synthetic_boundary_not_breached():
    res = evaluate_sla(plan="Enterprise", severity="P1", account_id=None, elapsed_minutes=30.0)
    assert res["target_string"] == "30 minutes, 24x7"
    assert res["breach_status"] == "not_breached"

def test_sla_03_synthetic_breached():
    res = evaluate_sla(plan="Enterprise", severity="P1", account_id=None, elapsed_minutes=31.0)
    assert res["target_string"] == "30 minutes, 24x7"
    assert res["breach_status"] == "breached"

def test_sla_04_synthetic_p2_breached():
    res = evaluate_sla(plan="Enterprise", severity="P2", account_id=None, elapsed_minutes=180.0)
    assert res["target_string"] == "2 hours, 24x7"
    assert res["breach_status"] == "breached"

def test_sla_05_synthetic_northstar_override_breached():
    res = evaluate_sla(plan="Enterprise", severity="P1", account_id="ACCT-001", elapsed_minutes=16.0)
    assert res["target_string"] == "15 minutes, 24x7"
    assert res["breach_status"] == "breached"
    assert any(r["rule_id"] == "sla_northstar_override" for r in res["applied_rules"])

def test_sla_06_synthetic_business_hours():
    res = evaluate_sla(plan="Growth", severity="P1", account_id=None, elapsed_minutes=300.0)
    assert res["target_string"] == "2 business hours"
    assert res["breach_status"] == "cannot_determine_without_business_hours_calendar"

def test_sla_northstar_p1_p2_p3():
    # Northstar P1
    res1 = evaluate_sla(plan="Enterprise", severity="P1", account_id="ACCT-001", elapsed_minutes=0.0)
    assert res1["target_string"] == "15 minutes, 24x7"
    # Northstar P2
    res2 = evaluate_sla(plan="Enterprise", severity="P2", account_id="ACCT-001", elapsed_minutes=0.0)
    assert res2["target_string"] == "1 hours, 24x7"
    # Northstar P3
    res3 = evaluate_sla(plan="Enterprise", severity="P3", account_id="ACCT-001", elapsed_minutes=0.0)
    assert res3["target_string"] == "8 business hours"

def test_sla_account_fallback():
    # ACCT-003, ACCT-004, and unknown should use default Enterprise
    for acc in ["ACCT-003", "ACCT-004", "UNKNOWN_ACC"]:
        res = evaluate_sla(plan="Enterprise", severity="P1", account_id=acc, elapsed_minutes=0.0)
        assert res["target_string"] == "30 minutes, 24x7"
        assert not any(r["rule_id"] == "sla_northstar_override" for r in res["applied_rules"])


# --- Cancellation Tests ---

def test_cancellation_northstar_override():
    res = evaluate_cancellation(status="BOOKED", minutes_since_booking=100.0, account_id="ACCT-001")
    assert res["eligible"] is True
    assert res["fee_inr"] == 0
    assert any(r["rule_id"] == "cancellation_northstar_override" for r in res["applied_rules"])

def test_cancellation_lumenworks_default():
    res = evaluate_cancellation(status="BOOKED", minutes_since_booking=31.0, account_id="ACCT-002")
    assert res["eligible"] is True
    assert res["fee_inr"] == 250
    assert any(r["rule_id"] == "cancellation_default" for r in res["applied_rules"])

def test_cancellation_default_draft():
    res = evaluate_cancellation(status="DRAFT", minutes_since_booking=None, account_id=None)
    assert res["eligible"] is True
    assert res["fee_inr"] == 0

def test_cancellation_default_missing_time():
    res = evaluate_cancellation(status="BOOKED", minutes_since_booking=None, account_id=None)
    assert res["eligible"] is None

def test_cancellation_boundaries():
    # Exactly 30.0 mins -> free
    res1 = evaluate_cancellation(status="BOOKED", minutes_since_booking=30.0, account_id=None)
    assert res1["fee_inr"] == 0
    # 30.001 mins -> 250 fee
    res2 = evaluate_cancellation(status="BOOKED", minutes_since_booking=30.001, account_id=None)
    assert res2["fee_inr"] == 250

def test_cancellation_account_fallback():
    for acc in ["ACCT-003", "ACCT-004", "UNKNOWN"]:
        res = evaluate_cancellation(status="BOOKED", minutes_since_booking=35.0, account_id=acc)
        assert res["fee_inr"] == 250


# --- Credit Tests ---

def test_credit_default():
    res = evaluate_credit(delay_hours=3.0, carrier_fault=True, customer_fault=False, shipment_fee_inr=2000.0, account_id=None)
    assert res["eligible"] is True
    assert res["credit_amount_inr"] == 200.0
    assert res["manager_approval_required"] is False
    assert any(r["rule_id"] == "credit_amount_default" for r in res["applied_rules"])

def test_credit_boundaries():
    # Exactly 2.0 hours -> not eligible
    res1 = evaluate_credit(delay_hours=2.0, carrier_fault=True, customer_fault=False, shipment_fee_inr=2000.0, account_id=None)
    assert res1["eligible"] is False
    # 2.001 hours -> eligible
    res2 = evaluate_credit(delay_hours=2.001, carrier_fault=True, customer_fault=False, shipment_fee_inr=2000.0, account_id=None)
    assert res2["eligible"] is True

def test_credit_missing_shipment_fee_default():
    res = evaluate_credit(delay_hours=3.0, carrier_fault=True, customer_fault=False, shipment_fee_inr=None, account_id=None)
    assert res["eligible"] is None
    assert "Missing shipment_fee_inr" in res["reasoning"]

def test_credit_lumenworks_override_missing_fee():
    # LumenWorks has a fixed amount, so it bypasses the need for shipment_fee_inr
    res = evaluate_credit(delay_hours=4.5, carrier_fault=True, customer_fault=False, shipment_fee_inr=None, account_id="ACCT-002")
    assert res["eligible"] is True
    assert res["credit_amount_inr"] == 300.0

def test_credit_missing_facts():
    res = evaluate_credit(delay_hours=None, carrier_fault=True, customer_fault=False, shipment_fee_inr=2000.0, account_id=None)
    assert res["eligible"] is None
    assert res["credit_amount_inr"] is None

def test_credit_manager_approval_boundaries():
    # Manager approval is for > 1000
    
    # We test it by mocking or just supplying a huge amount if there were an override.
    # Since we can't get >500 naturally due to the 500 cap on default rule, we can test it 
    # via a temporary override in ACCOUNT_TERMS for testing, or checking if we can pass a custom account.
    
    # Let's inject a test account into ACCOUNT_TERMS for this test
    ACCOUNT_TERMS["TEST-MGR"] = {
        "credit_amount_fixed": 1000.0
    }
    res_exact = evaluate_credit(delay_hours=3.0, carrier_fault=True, customer_fault=False, shipment_fee_inr=None, account_id="TEST-MGR")
    assert res_exact["credit_amount_inr"] == 1000.0
    assert res_exact["manager_approval_required"] is False
    
    ACCOUNT_TERMS["TEST-MGR"]["credit_amount_fixed"] = 1000.01
    res_above = evaluate_credit(delay_hours=3.0, carrier_fault=True, customer_fault=False, shipment_fee_inr=None, account_id="TEST-MGR")
    assert res_above["credit_amount_inr"] == 1000.01
    assert res_above["manager_approval_required"] is True
    
    # Clean up
    del ACCOUNT_TERMS["TEST-MGR"]

def test_credit_account_fallback():
    for acc in ["ACCT-003", "ACCT-004", "UNKNOWN"]:
        res = evaluate_credit(delay_hours=3.0, carrier_fault=True, customer_fault=False, shipment_fee_inr=1000.0, account_id=acc)
        assert res["eligible"] is True
        assert res["credit_amount_inr"] == 100.0  # 10% of 1000
