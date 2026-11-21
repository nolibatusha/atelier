"""Payment provider registry.

To add a real provider (Stripe, PayPal, a local PSP...):
  1. subclass PaymentProvider in a new module,
  2. register it in PROVIDERS below,
  3. add a payment method in Admin > Settings that points to its `code`.
The order/payment bookkeeping in services/orders.py does not change.
"""
from .base import PaymentProvider, PaymentResult  # noqa: F401
from .cod import CashOnDeliveryProvider
from .simulated import SimulatedProvider

PROVIDERS = {
    SimulatedProvider.code: SimulatedProvider(),
    CashOnDeliveryProvider.code: CashOnDeliveryProvider(),
}


def get_provider(code):
    """Registry lookup (used for display/bookkeeping)."""
    return PROVIDERS.get(code)


def get_usable_provider(code):
    """Provider that may actually take payments right now.

    The simulated provider lets the *customer* choose the outcome, so in production it is refused unless the
    operator explicitly opts in with ALLOW_SIMULATED_PAYMENTS=1 (e.g. on a staging/demo deployment).
    """
    from flask import current_app, has_app_context

    provider = PROVIDERS.get(code)
    if provider is not None and provider.is_simulated and has_app_context():  # CLI/seed runs have no web context
        if current_app.config.get("ENV") == "production" and not current_app.config.get("ALLOW_SIMULATED_PAYMENTS"):
            return None
    return provider
