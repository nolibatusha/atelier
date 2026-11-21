import secrets

from .base import PaymentProvider, PaymentResult

# Outcomes the demo "provider" can be told to produce.
OUTCOMES = {
    "success": None,
    "declined": "Card declined (simulated).",
    "insufficient_funds": "Insufficient funds (simulated).",
    "error": "Payment provider error (simulated).",
}


class SimulatedProvider(PaymentProvider):
    """Demo provider. Never handles card data and never moves money."""

    code = "simulated"
    label = "Simulated payment (demo)"
    is_simulated = True
    requires_payment_step = True

    def process(self, order, payload):
        outcome = (payload or {}).get("outcome", "success")
        if outcome not in OUTCOMES:
            outcome = "error"
        ref = "SIM-" + secrets.token_hex(6).upper()
        if outcome == "success":
            return PaymentResult(True, provider_ref=ref)
        return PaymentResult(False, provider_ref=ref, failure_reason=OUTCOMES[outcome])
