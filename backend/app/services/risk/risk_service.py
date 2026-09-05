import os
import json
import uuid
import numpy as np
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.payment import Payment
from app.models.risk_assessment import RiskAssessment
from app.models.audit_event import AuditEvent
from app.services.risk.feature_extractor import FeatureExtractor
from app.utils.logger import logger

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ml", "models")
KERAS_PATH = os.path.join(MODEL_DIR, "risk_classifier.keras")
WEIGHTS_PATH = os.path.join(MODEL_DIR, "model_weights.json")

class RiskAssessmentService:
    _keras_model = None
    _weights_cache = None

    @classmethod
    def _load_model(cls):
        # 1. Try loading Keras model if file exists
        if cls._keras_model is None and os.path.exists(KERAS_PATH):
            try:
                import tensorflow as tf
                from tensorflow import keras
                cls._keras_model = keras.models.load_model(KERAS_PATH)
                logger.info(f"Loaded Keras model artifact from {KERAS_PATH}")
            except Exception as e:
                logger.warning(f"Keras model present but could not be loaded via tensorflow: {e}")

        # 2. Fallback to pre-calibrated JSON weights
        if cls._weights_cache is None and os.path.exists(WEIGHTS_PATH):
            try:
                with open(WEIGHTS_PATH, "r") as f:
                    cls._weights_cache = json.load(f)
                logger.info(f"Loaded JSON model weights from {WEIGHTS_PATH}")
            except Exception as e:
                logger.error(f"Failed to read model weights JSON: {e}")

    @classmethod
    def compute_risk_score(cls, payment: Payment):
        """
        Pure inference pipeline: extracts features and runs deterministic model scoring.
        Returns (score, risk_level, model_version, explanation, feature_dict, signals).
        """
        cls._load_model()
        customer = payment.customer
        vector, feature_dict, signals = FeatureExtractor.extract_features(payment, customer)

        score: float = 0.50
        model_version: str = "Deterministic-v1.0"

        # Inference using Keras
        if cls._keras_model is not None:
            try:
                pred = cls._keras_model.predict(vector, verbose=0)
                score = float(pred[0][0])
                model_version = "Keras-DeepNeuralNetwork-v1.0"
            except Exception as e:
                logger.error(f"Keras inference failed: {e}, falling back to linear weights")

        # Inference using JSON Weights (Scikit-Learn Logistic Function)
        if cls._keras_model is None and cls._weights_cache is not None:
            coefs = np.array(cls._weights_cache.get("coefficients", []), dtype=np.float32)
            intercept = float(cls._weights_cache.get("intercept", 0.0))
            if len(coefs) == vector.shape[1]:
                logit = float(np.dot(vector[0], coefs) + intercept)
                score = float(1.0 / (1.0 + np.exp(-logit)))
                model_version = cls._weights_cache.get("model_version", "LogisticRegression-v1.0")

        # Fallback heuristic if neither is available
        if cls._keras_model is None and cls._weights_cache is None:
            score = 0.85 if payment.error_code == "CARD_VELOCITY_EXCEEDED" else (0.18 if (customer.lifetime_successful_orders or 0) > 1 else 0.45)
            model_version = "RuleHeuristic-v1.0"

        # Clip score between 0.01 and 0.99
        score = float(np.clip(score, 0.01, 0.99))

        # Assign Risk Level based on strict safety thresholds
        if score < 0.35:
            risk_level = "LOW"
            explanation = "Transaction exhibits low risk probability. Safe for automated recovery execution."
        elif score < 0.70:
            risk_level = "MEDIUM"
            explanation = "Moderate risk signals detected. Requires interactive smart link or secondary status verification."
        else:
            risk_level = "HIGH"
            explanation = "High risk or anomalous vector identified. Blocked from automated charge and quarantined for human review."

        return score, risk_level, model_version, explanation, feature_dict, signals

    @classmethod
    def evaluate_payment_risk(cls, db: Session, payment: Payment) -> RiskAssessment:
        """
        Extract features from payment and customer records, execute inference,
        and save/update the RiskAssessment record.
        """
        score, risk_level, model_version, explanation, feature_dict, signals = cls.compute_risk_score(payment)

        # Update or create RiskAssessment in database
        existing_risk = db.query(RiskAssessment).filter(RiskAssessment.payment_id == payment.id).first()

        if existing_risk:
            existing_risk.risk_score = round(score, 4)
            existing_risk.risk_level = risk_level
            existing_risk.model_version = model_version
            existing_risk.features_used = feature_dict
            existing_risk.signals = signals
            existing_risk.explanation = explanation
            risk_record = existing_risk
        else:
            risk_record = RiskAssessment(
                id=f"risk_{uuid.uuid4().hex[:10]}",
                payment_id=payment.id,
                risk_score=round(score, 4),
                risk_level=risk_level,
                model_version=model_version,
                features_used=feature_dict,
                signals=signals,
                explanation=explanation
            )
            db.add(risk_record)

        # Update Payment status if high risk
        if risk_level == "HIGH" and payment.recovery_status != "RECOVERED":
            payment.recovery_status = "IN_REVIEW"

        # Log Audit Event
        audit = AuditEvent(
            id=f"aud_{uuid.uuid4().hex[:10]}",
            payment_id=payment.id,
            event_type="RISK_EVALUATION",
            actor=f"Risk Classifier ({model_version})",
            details=f"Evaluated risk score: {score:.2f} ({risk_level}). Signals: {', '.join(signals) if signals else 'None'}",
            risk_level=risk_level,
            outcome="PASSED" if risk_level != "HIGH" else "QUARANTINED",
            metadata_json={"features": feature_dict, "score": score}
        )
        db.add(audit)
        db.commit()
        db.refresh(risk_record)

        logger.info(f"Risk evaluation complete for {payment.id}: Score {score:.4f} ({risk_level}) via {model_version}")
        return risk_record
