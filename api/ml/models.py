"""
ML models for resource prediction.
Implements regression models for memory, time, and CPU prediction.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler
import joblib
import json
import os
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime, timezone


class ResourcePredictor:
    """
    ML-based resource predictor for Nextflow processes.
    Trains models to predict memory, time, and CPU requirements.
    """
    
    def __init__(self, model_dir: str = "/code/models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        print(f"📦 Model directory: {self.model_dir}")
        
        self.models = {
            'memory': None,
            'time': None,
            'cpu': None,
        }
        self.scalers = {
            'memory': None,
            'time': None,
            'cpu': None,
        }
        self.feature_columns = {}
        self.model_metadata = {}
    
    def train_model(
        self, 
        X: pd.DataFrame, 
        y: pd.Series, 
        model_type: str = 'memory',
        model_name: str = 'gradient_boosting',
        loss: str = 'squared_error',
        alpha: float = 0.95,
        sample_weights: Optional[pd.Series] = None,
        model_key_suffix: str = ''
    ) -> Dict:
        """
        Train a prediction model for a specific resource type.
        
        Args:
            X: Feature matrix
            y: Target variable
            model_type: 'memory', 'time', or 'cpu'
            model_name: 'gradient_boosting', 'random_forest', or 'ridge'
            loss: 'squared_error' for mean, 'quantile' for percentile
            alpha: For quantile loss, which percentile (0.95 = P95)
            sample_weights: Optional sample weights for prioritizing failures
        
        Returns:
            Dictionary with training metrics
        """
        
        # Remove rows with invalid targets
        valid_mask = y.notna() & (y > 0)
        X_valid = X[valid_mask].copy()
        y_valid = y[valid_mask].copy()
        weights_valid = sample_weights[valid_mask] if sample_weights is not None else None
        
        if len(X_valid) < 10:
            return {
                'error': f'Insufficient training data: {len(X_valid)} samples',
                'success': False
            }
        
        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X_valid, y_valid, test_size=0.2, random_state=42
        )
        
        # Split weights if provided
        if weights_valid is not None:
            weights_train = weights_valid[:len(X_train)]
            weights_test = weights_valid[len(X_train):]
        else:
            weights_train = None
            weights_test = None
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Select model
        if model_name == 'gradient_boosting':
            if loss == 'quantile':
                model = GradientBoostingRegressor(
                    loss='quantile',
                    alpha=alpha,  # P95 by default
                    n_estimators=100,
                    max_depth=5,
                    learning_rate=0.1,
                    random_state=42
                )
            else:
                model = GradientBoostingRegressor(
                    loss='squared_error',
                    n_estimators=100,
                    max_depth=5,
                    learning_rate=0.1,
                    random_state=42
                )
        elif model_name == 'random_forest':
            model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
        elif model_name == 'ridge':
            model = Ridge(alpha=1.0)
        else:
            raise ValueError(f"Unknown model: {model_name}")
        
        # Train model with optional sample weights
        if weights_train is not None:
            model.fit(X_train_scaled, y_train, sample_weight=weights_train)
        else:
            model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred_train = model.predict(X_train_scaled)
        y_pred_test = model.predict(X_test_scaled)
        
        # Cross-validation (without weights for simplicity)
        cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=5, scoring='r2')
        
        # Calculate metrics
        metrics = {
            'model_type': model_type,
            'model_name': model_name,
            'loss': loss,
            'alpha': alpha if loss == 'quantile' else None,
            'training_samples': len(X_train),
            'test_samples': len(X_test),
            'train_rmse': np.sqrt(mean_squared_error(y_train, y_pred_train)),
            'train_mae': mean_absolute_error(y_train, y_pred_train),
            'train_r2': r2_score(y_train, y_pred_train),
            'test_rmse': np.sqrt(mean_squared_error(y_test, y_pred_test)),
            'test_mae': mean_absolute_error(y_test, y_pred_test),
            'test_r2': r2_score(y_test, y_pred_test),
            'cv_r2_mean': cv_scores.mean(),
            'cv_r2_std': cv_scores.std(),
            'feature_importance': dict(zip(
                X.columns, 
                model.feature_importances_.tolist() if hasattr(model, 'feature_importances_') else [0] * len(X.columns)
            )),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'success': True,
        }
        
        # Store model and scaler with appropriate key
        # Use suffix for different quantiles (e.g., time_quantile_p95, time_quantile_p99)
        if loss == 'quantile' and model_key_suffix:
            model_key = f'{model_type}_quantile{model_key_suffix}'
        elif loss == 'quantile':
            model_key = f'{model_type}_quantile'
        else:
            model_key = f'{model_type}_mean'
        
        self.models[model_key] = model
        self.scalers[model_key] = scaler
        self.feature_columns[model_type] = X.columns.tolist()
        self.model_metadata[model_type] = metrics
        
        print(f"  Trained {model_key} with {len(X)} samples")
        
        return metrics
    
    def _calculate_confidence(
        self, 
        feature_df: pd.DataFrame, 
        model_type: str,
        prediction: float
    ) -> float:
        """
        Calculate confidence score for a prediction based on:
        1. Model's historical performance (R², CV scores)
        2. Training sample count
        3. Feature validity (no missing/zero features)
        
        Returns: Confidence score between 0.0 and 1.0
        """
        confidence = 0.5  # Base confidence
        
        # Factor 1: Model performance (R² score)
        metadata = self.model_metadata.get(model_type, {})
        if metadata.get('success'):
            r2 = metadata.get('test_r2', 0)
            cv_r2 = metadata.get('cv_r2_mean', 0)
            
            # R² contribution (up to 0.3 points)
            # R² > 0.8: +0.3, R² > 0.6: +0.2, R² > 0.4: +0.1
            if r2 > 0.8:
                confidence += 0.3
            elif r2 > 0.6:
                confidence += 0.2
            elif r2 > 0.4:
                confidence += 0.1
            
            # CV consistency (up to 0.1 points)
            # Low std dev means model is stable
            cv_std = metadata.get('cv_r2_std', 1.0)
            if cv_std < 0.05:
                confidence += 0.1
            elif cv_std < 0.1:
                confidence += 0.05
        
        # Factor 2: Training sample count (up to 0.2 points)
        training_samples = metadata.get('training_samples', 0)
        if training_samples >= 500:
            confidence += 0.2
        elif training_samples >= 100:
            confidence += 0.15
        elif training_samples >= 50:
            confidence += 0.1
        elif training_samples >= 10:
            confidence += 0.05
        
        # Factor 3: Feature validity (up to 0.1 points)
        # Check if features have reasonable values (not all zeros/NaN)
        feature_valid_ratio = (feature_df != 0).mean().mean() if not feature_df.empty else 0
        if feature_valid_ratio > 0.8:
            confidence += 0.1
        elif feature_valid_ratio > 0.5:
            confidence += 0.05
        
        # Cap confidence at 1.0
        return min(1.0, confidence)
    
    def predict(
        self, 
        features: Dict, 
        model_type: str = 'memory',
        confidence: bool = True
    ) -> Dict:
        """
        Predict resource requirements with resource-specific percentiles.
        
        Resource strategies:
        - Memory: P95 (avoid OOM kills)
        - Time: P95 and P99 (timeout kills job) + minimum 1 hour + scale with data size
        - CPU: P75 (efficient utilization, 70-90% per-core)
        
        Args:
            features: Dictionary of feature values
            model_type: 'memory', 'time', or 'cpu'
            confidence: Whether to calculate confidence interval
        
        Returns:
            Dictionary with mean and percentile predictions
        """
        
        # Check if models exist
        mean_model_key = f'{model_type}_mean'
        
        if mean_model_key not in self.models:
            return {
                'error': f'Models not trained for {model_type}',
                'success': False
            }
        
        # Convert features to DataFrame
        feature_df = pd.DataFrame([features])
        
        # Ensure all expected columns are present
        expected_cols = self.feature_columns.get(model_type, [])
        for col in expected_cols:
            if col not in feature_df.columns:
                feature_df[col] = 0
        
        # Reorder columns to match training
        feature_df = feature_df[expected_cols]
        
        # Scale features (use mean model's scaler)
        scaler = self.scalers[mean_model_key]
        feature_scaled = scaler.transform(feature_df)
        
        # Get mean prediction
        mean_model = self.models[mean_model_key]
        mean_pred = mean_model.predict(feature_scaled)[0]
        
        # Get percentile predictions based on resource type
        result = {
            'prediction_mean': float(mean_pred),
            'success': True
        }
        
        if model_type == 'memory':
            # Memory: P95 (avoid OOM)
            p95_key = f'{model_type}_quantile'
            if p95_key in self.models:
                p95_model = self.models[p95_key]
                p95_pred = p95_model.predict(feature_scaled)[0]
                result['prediction_p95'] = float(p95_pred)
                result['percentile_used'] = 'p95'
                result['safety_margin'] = float(p95_pred / max(mean_pred, 1))
            else:
                result['success'] = False
                result['error'] = 'P95 model not trained'
                
        elif model_type == 'time':
            # Time: BOTH P95 and P99 (user can choose based on risk tolerance)
            p95_key = f'{model_type}_quantile_p95'
            p99_key = f'{model_type}_quantile_p99'
            
            # Try to get P99 model first (most conservative)
            if p99_key in self.models:
                p99_model = self.models[p99_key]
                p99_pred = p99_model.predict(feature_scaled)[0]
                result['prediction_p99'] = float(p99_pred)
            else:
                result['prediction_p99'] = 0.0
                
            # Get P95 model
            if p95_key in self.models:
                p95_model = self.models[p95_key]
                p95_pred = p95_model.predict(feature_scaled)[0]
                result['prediction_p95'] = float(p95_pred)
            else:
                result['prediction_p95'] = 0.0
            
            # CRITICAL: Time is a KILL LIMIT - enforce minimum 1 hour (3600s)
            # Scale minimum based on data size (larger data = more time needed)
            disk_usage_mb = features.get('disk_usage_mb', 0) or 0
            io_total = features.get('io_total', 0) or 0
            
            # Base minimum: 1 hour
            time_minimum = 3600
            
            # Scale minimum for large data (>10GB = 2hr min, >100GB = 4hr min)
            if disk_usage_mb > 100000:  # >100GB
                time_minimum = 14400  # 4 hours
            elif disk_usage_mb > 10000:  # >10GB
                time_minimum = 7200  # 2 hours
            
            # Apply minimum to all time predictions
            if 'prediction_p99' in result:
                result['prediction_p99'] = max(result['prediction_p99'], time_minimum)
            if 'prediction_p95' in result:
                result['prediction_p95'] = max(result['prediction_p95'], time_minimum)
            result['prediction_mean'] = max(result['prediction_mean'], time_minimum)
            
            result['percentile_used'] = 'p99'  # Primary recommendation
            result['time_minimum_applied'] = time_minimum
            result['safety_margin'] = float(result.get('prediction_p99', mean_pred) / max(mean_pred, 1))
            
        elif model_type == 'cpu':
            # CPU: P75 (efficient utilization)
            p75_key = f'{model_type}_quantile_p75'
            if p75_key in self.models:
                p75_model = self.models[p75_key]
                p75_pred = p75_model.predict(feature_scaled)[0]
                # Round to integer, minimum 1
                p75_pred = max(1, round(p75_pred))
                result['prediction_p75'] = float(p75_pred)
                result['percentile_used'] = 'p75'
                result['safety_margin'] = float(p75_pred / max(mean_pred, 1))
            else:
                result['success'] = False
                result['error'] = 'P75 model not trained'
        
        # Calculate confidence score
        primary_pred = result.get(f"prediction_{result.get('percentile_used', 'p95')}", mean_pred)
        confidence_score = self._calculate_confidence(
            feature_df, model_type, primary_pred
        )
        result['confidence'] = confidence_score
        result['confidence_level'] = 'high' if confidence_score >= 0.8 else ('medium' if confidence_score >= 0.5 else 'low')
        result['model_version'] = self.model_metadata.get(model_type, {}).get('timestamp', 'unknown')
        
        # Add confidence interval
        if confidence and 'test_rmse' in self.model_metadata.get(model_type, {}):
            rmse = self.model_metadata[model_type]['mean_model']['test_rmse']
            result['confidence_interval'] = {
                'lower': float(max(0, mean_pred - 1.96 * rmse)),
                'upper': float(primary_pred),
                'confidence_level': 0.95 if model_type != 'time' else 0.99
            }
        
        return result
    
    def save_models(self):
        """Save trained models to disk (supports multiple quantiles per resource)."""
        # Save all models in self.models dictionary
        for model_key, model in self.models.items():
            if model is not None:
                model_path = self.model_dir / f"{model_key}_model.joblib"
                scaler_path = self.model_dir / f"{model_key}_scaler.joblib"
                
                joblib.dump(model, model_path)
                if model_key in self.scalers:
                    joblib.dump(self.scalers[model_key], scaler_path)
        
        # Save metadata
        metadata_path = self.model_dir / "all_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(self.model_metadata, f, indent=2)
        
        # Save feature columns
        features_path = self.model_dir / "all_features.json"
        with open(features_path, 'w') as f:
            json.dump(self.feature_columns, f, indent=2)
        
        print(f"✓ Saved {len(self.models)} models to {self.model_dir}")
    
    def load_models(self):
        """Load trained models from disk (supports multiple quantiles per resource)."""
        model_files = list(self.model_dir.glob("*_model.joblib"))
        
        for model_path in model_files:
            # Extract model key from filename (e.g., "time_quantile_p99_model.joblib" -> "time_quantile_p99")
            model_key = model_path.stem.replace('_model', '')
            
            model = joblib.load(model_path)
            self.models[model_key] = model
            
            # Load corresponding scaler if exists
            scaler_path = model_path.parent / f"{model_key}_scaler.joblib"
            if scaler_path.exists():
                self.scalers[model_key] = joblib.load(scaler_path)
        
        # Load metadata
        metadata_path = self.model_dir / "all_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                self.model_metadata = json.load(f)
        
        # Load feature columns
        features_path = self.model_dir / "all_features.json"
        if features_path.exists():
            with open(features_path, 'r') as f:
                self.feature_columns = json.load(f)
        
        print(f"✓ Loaded {len(self.models)} models from {self.model_dir}")
        print(f"  Model keys: {list(self.models.keys())}")


def train_all_models(df: pd.DataFrame, model_dir: str = None, prioritize_failures: bool = True) -> Dict:
    """
    Train all resource prediction models with quantile regression.
    
    Args:
        df: DataFrame with features and targets
        model_dir: Directory to save models
        prioritize_failures: If True, weight failure data points higher
    
    Returns:
        Dictionary with training results for all models
    """
    
    from ml.features import prepare_training_data
    
    predictor = ResourcePredictor(model_dir=model_dir)
    results = {}
    
    # Prepare sample weights if failures exist
    sample_weights = None
    failure_count = 0
    if prioritize_failures and 'failure_reason' in df.columns:
        sample_weights = pd.Series(1.0, index=df.index)
        failure_mask = df['failure_reason'].notna()
        sample_weights[failure_mask] = 2.0  # 2x weight for failures
        failure_count = failure_mask.sum()
        print(f"⚠️  Prioritizing {failure_count} failure data points (2x weight)")
    
    # Train memory model (P95 - avoid OOM kills)
    print("Training memory prediction models...")
    X_mem, y_mem, features_mem = prepare_training_data(df, 'target_memory_mb')
    if len(X_mem) > 10:
        # Train mean model
        metrics_mem_mean = predictor.train_model(X_mem, y_mem, 'memory', loss='squared_error', sample_weights=sample_weights)
        # Train P95 model (conservative - OOM is catastrophic)
        metrics_mem_p95 = predictor.train_model(X_mem, y_mem, 'memory', loss='quantile', alpha=0.95, sample_weights=sample_weights)
        
        results['memory'] = {
            'mean_model': metrics_mem_mean,
            'p95_model': metrics_mem_p95,
            'success': True
        }
        print(f"  ✓ Memory mean model R²: {metrics_mem_mean.get('test_r2', 0):.3f}")
        print(f"  ✓ Memory P95 model R²: {metrics_mem_p95.get('test_r2', 0):.3f}")
    else:
        results['memory'] = {'error': 'Insufficient data', 'success': False}
        print(f"  ✗ Insufficient data for memory model")
    
    # Train time model (BOTH P95 and P99 - time is KILL LIMIT)
    print("Training time prediction models...")
    X_time, y_time, features_time = prepare_training_data(df, 'target_duration_sec')
    if len(X_time) > 10:
        # Train mean model
        metrics_time_mean = predictor.train_model(X_time, y_time, 'time', loss='squared_error', sample_weights=sample_weights)
        
        # Train P95 model (conservative)
        metrics_time_p95 = predictor.train_model(X_time, y_time, 'time', loss='quantile', alpha=0.95, sample_weights=sample_weights, model_key_suffix='_p95')
        
        # Train P99 model (EXTREMELY conservative - timeout kills job)
        # Weight timeout failures 5x higher (catastrophic failure)
        time_weights = sample_weights.copy() if sample_weights is not None else pd.Series(1.0, index=df.index)
        
        # Detect timeout failures safely (handle missing column and mixed types)
        if 'failure_reason' in df.columns:
            timeout_mask = df['failure_reason'].fillna('').astype(str).str.contains('timeout|time|killed|signal', case=False, na=False)
        else:
            timeout_mask = pd.Series(False, index=df.index)
        
        time_weights[timeout_mask] = 5.0  # 5x weight for timeout failures
        
        metrics_time_p99 = predictor.train_model(X_time, y_time, 'time', loss='quantile', alpha=0.99, sample_weights=time_weights, model_key_suffix='_p99')
        
        results['time'] = {
            'mean_model': metrics_time_mean,
            'p95_model': metrics_time_p95,
            'p99_model': metrics_time_p99,
            'success': True
        }
        print(f"  ✓ Time mean model R²: {metrics_time_mean.get('test_r2', 0):.3f}")
        print(f"  ✓ Time P95 model R²: {metrics_time_p95.get('test_r2', 0):.3f}")
        print(f"  ✓ Time P99 model R²: {metrics_time_p99.get('test_r2', 0):.3f}")
        print(f"  ⚠️  Weighted {timeout_mask.sum()} timeout failures 5x higher")
    else:
        results['time'] = {'error': 'Insufficient data', 'success': False}
        print(f"  ✗ Insufficient data for time model")
    
    # Train CPU model (P75 - efficient utilization, not over-provisioning)
    # CPU over-allocation wastes resources but doesn't kill jobs
    # Target 70-90% per-core utilization
    print("Training CPU prediction models...")
    X_cpu, y_cpu, features_cpu = prepare_training_data(df, 'target_cpus')
    if len(X_cpu) > 10:
        # Train mean model
        metrics_cpu_mean = predictor.train_model(X_cpu, y_cpu, 'cpu', loss='squared_error', sample_weights=sample_weights)
        # Train P75 model (moderate - allows efficient utilization)
        metrics_cpu_p75 = predictor.train_model(X_cpu, y_cpu, 'cpu', loss='quantile', alpha=0.75, sample_weights=sample_weights, model_key_suffix='_p75')
        
        results['cpu'] = {
            'mean_model': metrics_cpu_mean,
            'p75_model': metrics_cpu_p75,  # ← P75, not P95!
            'success': True
        }
        print(f"  ✓ CPU mean model R²: {metrics_cpu_mean.get('test_r2', 0):.3f}")
        print(f"  ✓ CPU P75 model R²: {metrics_cpu_p75.get('test_r2', 0):.3f}")
    else:
        results['cpu'] = {'error': 'Insufficient data', 'success': False}
        print(f"  ✗ Insufficient data for CPU model")
    
    # Save models
    predictor.save_models()
    print(f"✓ Models saved to {model_dir}")
    
    # Add summary statistics
    results['summary'] = {
        'total_samples': len(df),
        'failure_samples': failure_count,
        'models_trained': sum(1 for v in results.values() if isinstance(v, dict) and v.get('success'))
    }
    
    return results
