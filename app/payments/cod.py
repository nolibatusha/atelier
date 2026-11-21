from .base import PaymentProvider, PaymentResult


class CashOnDeliveryProvider(PaymentProvider):
    """Offline payment: the order is confirmed now; cash is collected on delivery."""

    code = "cod"
    label = "Cash on delivery"
    requires_payment_step = False

    def process(self, order, payload):
        return PaymentResult(True, provider_ref=f"COD-{order['number']}")
