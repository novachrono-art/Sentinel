from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class PaymentProvider(ABC):
    """
    Abstract Payment Gateway Provider interface.
    Decouples payment orchestration and agent recovery from external gateway APIs.
    """

    @abstractmethod
    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        """Fetch full payment details from gateway."""
        pass

    @abstractmethod
    def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Fetch standardized status and state of payment."""
        pass

    @abstractmethod
    def create_order(
        self,
        amount: float,
        currency: str,
        receipt: str,
        notes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new payment order with the gateway."""
        pass

    @abstractmethod
    def create_payment_link(
        self,
        amount: float,
        currency: str,
        customer_name: str,
        customer_email: str,
        description: str,
        idempotency_key: str,
        customer_phone: Optional[str] = None,
        expire_by_hours: int = 24
    ) -> Dict[str, Any]:
        """Generate a smart recovery payment link for customer retry."""
        pass

    @abstractmethod
    def retry_payment(self, payment_id: str, idempotency_key: str) -> Dict[str, Any]:
        """Execute a safe automated retry against the gateway switch."""
        pass

    @abstractmethod
    def verify_webhook_signature(self, payload_body: bytes, signature: str, secret: str) -> bool:
        """Cryptographically verify the incoming webhook signature."""
        pass

    # Backwards compatibility alias
    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        return self.get_payment(payment_id)
