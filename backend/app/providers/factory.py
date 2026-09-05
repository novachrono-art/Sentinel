from app.providers.base import PaymentProvider
from app.providers.razorpay_provider import RazorpayProvider
from app.providers.demo_provider import DemoPaymentProvider
from app.config.settings import settings

def get_payment_provider() -> PaymentProvider:
    """
    Factory function resolving active payment provider based on configuration.
    """
    mode = getattr(settings, "RAZORPAY_MODE", "test").lower()
    if mode in ["live", "test"]:
        return RazorpayProvider()
    return DemoPaymentProvider()
