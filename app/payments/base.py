from dataclasses import dataclass


@dataclass
class PaymentResult:
    success: bool
    provider_ref: str = ""
    failure_reason: str = ""


class PaymentProvider:
    """Interface every payment integration implements."""

    code = ""
    label = ""
    is_simulated = False
    # True => the customer must complete a separate payment step after the order is created
    # (hosted page, redirect, 3-D Secure...). False => order is confirmed immediately (e.g. COD).
    requires_payment_step = False

    def process(self, order, payload):
        """Attempt to take payment for `order` (a sqlite Row/dict). Must NOT touch the database;
        services/orders.py records the outcome atomically. Return a PaymentResult."""
        raise NotImplementedError

    def refund(self, order, payment):
        """Optional: reverse a payment. Return a PaymentResult."""
        return PaymentResult(True, provider_ref=f"refund-{payment['provider_ref']}")
