"""
=============================================================================
Payment Failure Risk Classifier — Model Training Script (Google Colab / Local)
=============================================================================
This script trains a deterministic Risk Classification Model on payment failure features.
It evaluates precision, recall, and ROC-AUC, then exports the model weights.

Output Model Destination:
  backend/app/ml/models/risk_classifier.keras
  backend/app/ml/models/model_weights.json
=============================================================================
"""

import os
import json
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, confusion_matrix
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# Ensure output directories exist
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "app", "ml", "models")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOCAL_ML_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(LOCAL_ML_DIR, exist_ok=True)

def generate_synthetic_dataset(num_samples: int = 10000, random_seed: int = 42):
    """
    Generate realistic payment failure dataset with calibrated risk correlations.
    
    Features:
      0. amount_scaled (0.0 - 1.0)
      1. order_history_count (0 - 20)
      2. dispute_count (0 - 5)
      3. velocity_score (0.0 - 1.0)
      4. disposable_email (0 or 1)
      5. error_severity (0.1 = temporary, 0.9 = fraud/velocity)
      6. retry_ratio (0.0 - 1.0)
      7. lifetime_spend_scaled (0.0 - 1.0)
    """
    np.random.seed(random_seed)
    
    # Feature 0: Amount (Log-normal distribution)
    amounts = np.random.lognormal(mean=8.5, sigma=1.2, size=num_samples)
    amounts = np.clip(amounts, 100, 200000)
    amount_scaled = (amounts - 100) / (200000 - 100)
    
    # Feature 1: Customer Order History (Poisson)
    order_history = np.random.poisson(lam=3.5, size=num_samples)
    
    # Feature 2: Dispute Count
    dispute_count = np.random.binomial(n=3, p=0.05, size=num_samples)
    
    # Feature 3: Velocity Score (0.0 = normal, 1.0 = rapid burst)
    velocity_score = np.random.beta(a=1.5, b=6.0, size=num_samples)
    
    # Feature 4: Disposable Email Flag (1 = burner domain, 0 = legit)
    disposable_email = np.random.binomial(n=1, p=0.08, size=num_samples)
    
    # Feature 5: Error Severity (0.1 = temporary bank decline, 0.5 = timeout, 0.9 = card blocked/velocity)
    error_severity = np.random.choice([0.1, 0.25, 0.45, 0.7, 0.9], size=num_samples, p=[0.45, 0.25, 0.15, 0.10, 0.05])
    
    # Feature 6: Retry Ratio (Current retries / 3)
    retries = np.random.choice([0, 1, 2, 3], size=num_samples, p=[0.55, 0.25, 0.12, 0.08])
    retry_ratio = retries / 3.0
    
    # Feature 7: Lifetime Spend (correlated with order history)
    lifetime_spend = order_history * np.random.uniform(500, 3000, size=num_samples)
    lifetime_spend_scaled = np.clip(lifetime_spend / 50000.0, 0.0, 1.0)
    
    # Combine feature matrix (X)
    X = np.column_stack([
        amount_scaled,
        np.clip(order_history / 15.0, 0.0, 1.0),
        np.clip(dispute_count / 3.0, 0.0, 1.0),
        velocity_score,
        disposable_email,
        error_severity,
        retry_ratio,
        lifetime_spend_scaled
    ])
    
    # Calculate Ground Truth Risk Probability (Logit equation)
    logit = (
        2.2 * amount_scaled
        - 2.8 * (order_history / 15.0)
        + 3.5 * (dispute_count / 3.0)
        + 3.2 * velocity_score
        + 2.6 * disposable_email
        + 2.9 * error_severity
        + 1.8 * retry_ratio
        - 2.1 * lifetime_spend_scaled
        - 1.5 # Bias intercept
    )
    
    prob = 1.0 / (1.0 + np.exp(-logit))
    # Target label: 1 = High Risk / Non-recoverable, 0 = Safe / Recoverable
    y = (prob >= 0.50).astype(int)
    
    return X, y

def train_and_export_model():
    print("================================================================")
    print("Generating Synthetic Merchant Payment Failure Dataset...")
    X, y = generate_synthetic_dataset(num_samples=10000)
    print(f"Total Dataset Samples: {X.shape[0]} with {X.shape[1]} features")
    print(f"Class Balance: Safe (0) = {np.sum(y == 0)}, High Risk (1) = {np.sum(y == 1)}")
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42, stratify=y)
    
    print("\nTraining Deterministic Logistic Classifier...")
    lr_model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
    lr_model.fit(X_train, y_train)
    
    y_pred = lr_model.predict(X_test)
    y_prob = lr_model.predict_proba(X_test)[:, 1]
    
    auc = roc_auc_score(y_test, y_prob)
    cm = confusion_matrix(y_test, y_pred)
    
    print("\n---------------- Model Evaluation Metrics ----------------")
    print(f"ROC-AUC Score: {auc:.4f}")
    print("Confusion Matrix:")
    print(cm)
    print("\nDetailed Classification Report:")
    print(classification_report(y_test, y_pred, target_names=["Safe (Low Risk)", "Quarantine (High Risk)"]))
    
    # Try training Keras model if TensorFlow is available
    keras_saved = False
    try:
        import tensorflow as tf
        from tensorflow import keras
        from tensorflow.keras import layers
        
        print("\nTraining Keras Deep Neural Network Classifier...")
        keras_model = keras.Sequential([
            layers.Input(shape=(8,)),
            layers.Dense(32, activation="relu"),
            layers.Dropout(0.2),
            layers.Dense(16, activation="relu"),
            layers.Dense(1, activation="sigmoid")
        ])
        
        keras_model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=0.005),
            loss="binary_crossentropy",
            metrics=["accuracy", keras.metrics.AUC(name="auc")]
        )
        
        keras_model.fit(X_train, y_train, epochs=20, batch_size=64, validation_split=0.1, verbose=0)
        
        keras_path_1 = os.path.join(OUTPUT_DIR, "risk_classifier.keras")
        keras_path_2 = os.path.join(LOCAL_ML_DIR, "risk_classifier.keras")
        keras_model.save(keras_path_1)
        keras_model.save(keras_path_2)
        print(f"Saved Keras model artifact to: {keras_path_1}")
        keras_saved = True
    except ImportError:
        print("\nTensorFlow/Keras not installed in local environment — continuing with Scikit-Learn weights export.")

    # Export model weights & coefficients JSON for zero-dependency high-performance inference
    weights_data = {
        "model_type": "LogisticRegression",
        "model_version": "v1.0-deterministic",
        "features": [
            "amount_scaled",
            "order_history_scaled",
            "dispute_count_scaled",
            "velocity_score",
            "disposable_email",
            "error_severity",
            "retry_ratio",
            "lifetime_spend_scaled"
        ],
        "coefficients": lr_model.coef_[0].tolist(),
        "intercept": float(lr_model.intercept_[0]),
        "metrics": {
            "roc_auc": float(auc),
            "test_samples": len(y_test)
        },
        "thresholds": {
            "low_risk_ceiling": 0.35,
            "medium_risk_ceiling": 0.70,
            "high_risk_floor": 0.70
        }
    }
    
    weights_path_1 = os.path.join(OUTPUT_DIR, "model_weights.json")
    weights_path_2 = os.path.join(LOCAL_ML_DIR, "model_weights.json")
    
    with open(weights_path_1, "w") as f:
        json.dump(weights_data, f, indent=2)
    with open(weights_path_2, "w") as f:
        json.dump(weights_data, f, indent=2)
        
    print(f"Exported model weights JSON to: {weights_path_1}")
    print("================================================================")
    print("MODEL TRAINING & EXPORT COMPLETE!")
    print("Target placement for trained Keras / JSON weights:")
    print(f"-> {weights_path_1}")

if __name__ == "__main__":
    train_and_export_model()
