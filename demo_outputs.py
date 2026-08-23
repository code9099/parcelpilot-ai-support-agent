import json
from business_rules.cancellation import evaluate_cancellation
from business_rules.credit import evaluate_credit
from business_rules.sla import evaluate_sla
from business_rules.models import ACCOUNT_TERMS

print("=== ACCOUNT_TERMS ===")
print(json.dumps(ACCOUNT_TERMS, indent=2))
print("\n" + "="*50 + "\n")

print("=== Northstar Cancellation ===")
res = evaluate_cancellation("BOOKED", 100.0, "ACCT-001")
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")

print("=== LumenWorks Cancellation / Default ===")
res = evaluate_cancellation("BOOKED", 35.0, "ACCT-002")
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")

print("=== Default Credit ===")
res = evaluate_credit(3.0, True, False, 2000.0, None)
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")

print("=== LumenWorks Credit Override ===")
res = evaluate_credit(4.5, True, False, 9999.0, "ACCT-002")
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")

print("=== Missing Credit Facts ===")
res = evaluate_credit(None, True, False, 2000.0, None)
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")

print("=== Northstar SLA ===")
res = evaluate_sla("Enterprise", "P1", "ACCT-001", 16.0)
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")

print("=== Indeterminate Business-Hours SLA ===")
res = evaluate_sla("Growth", "P1", None, 180.0)
print(json.dumps(res, indent=2))
print("\n" + "="*50 + "\n")
