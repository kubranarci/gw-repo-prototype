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
        model_name: str = 'gradient_boosting'
    ) -> Dict:
        """
        Train a prediction model for a specific resource type.
        
        Args:
            X: Feature matrix
            y: Target variable
            model_type: 'memory', 'time', or 'cpu'
            model_name: 'gradient_boosting', 'random_forest', or 'ridge'
        
        Returns:
            Dictionary with training metrics
        """
        
        # Remove rows with invalid targets
        valid_mask = y.notna() & (y > 0)
        X_valid = X[valid_mask].copy()
        y_valid = y[valid_mask].copy()
        
        if len(X_valid) < 10:
            return {
                'error': f'Insufficient training data: {len(X_valid)} samples',
                'success': False
            }
        
        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X_valid, y_valid, test_size=0.2, random_state=42
        )
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Select model
        if model_name == 'gradient_boosting':
            model = GradientBoostingRegressor(
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
        
        # Train model
        model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred_train = model.predict(X_train_scaled)
        y_pred_test = model.predict(X_test_scaled)
        
        # Cross-validation
        cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=5, scoring='r2')
        
        # Calculate metrics
        metrics = {
            'model_type': model_type,
            'model_name': model_name,
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
        
        # Store model and scaler
        self.models[model_type] = model
        self.scalers[model_type] = scaler
        self.feature_columns[model_type] = X.columns.tolist()
        self.model_metadata[model_type] = metrics
        
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
        Predict resource requirements for a process.
        
        Args:
            features: Dictionary of feature values
            model_type: 'memory', 'time', or 'cpu'
            confidence: Whether to calculate confidence interval
        
        Returns:
            Dictionary with prediction and confidence interval
        """
        
        if self.models[model_type] is None:
            return {
                'error': f'Model not trained for {model_type}',
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
        
        # Scale features
        scaler = self.scalers[model_type]
        feature_scaled = scaler.transform(feature_df)
        
        # Predict
        model = self.models[model_type]
        prediction = model.predict(feature_scaled)[0]
        
        # Calculate confidence score based on multiple factors
        confidence_score = self._calculate_confidence(
            feature_df, model_type, prediction
        )
        
        # Apply safety margin based on confidence
        # Lower confidence → higher safety margin
        # High confidence (0.8+): 15% margin
        # Medium confidence (0.5-0.8): 30% margin  
        # Low confidence (<0.5): 50% margin
        if confidence_score >= 0.8:
            safety_margin = 1.15
        elif confidence_score >= 0.5:
            safety_margin = 1.30
        else:
            safety_margin = 1.50
        
        result = {
            'prediction': float(prediction),
            'prediction_with_safety': float(prediction * safety_margin),
            'safety_margin': safety_margin,
            'confidence': confidence_score,
            'confidence_level': 'high' if confidence_score >= 0.8 else ('medium' if confidence_score >= 0.5 else 'low'),
            'model_version': self.model_metadata.get(model_type, {}).get('timestamp', 'unknown'),
            'success': True
        }
        
        # Add confidence interval if requested
        if confidence and 'test_rmse' in self.model_metadata.get(model_type, {}):
            rmse = self.model_metadata[model_type]['test_rmse']
            result['confidence_interval'] = {
                'lower': float(max(0, prediction - 1.96 * rmse)),
                'upper': float(prediction + 1.96 * rmse),
                'confidence_level': 0.95
            }
        
        return result
    
    def save_models(self):
        """Save trained models to disk."""
        for model_type in ['memory', 'time', 'cpu']:
            if self.models[model_type] is not None:
                model_path = self.model_dir / f"{model_type}_model.joblib"
                scaler_path = self.model_dir / f"{model_type}_scaler.joblib"
                metadata_path = self.model_dir / f"{model_type}_metadata.json"
                features_path = self.model_dir / f"{model_type}_features.json"
                
                joblib.dump(self.models[model_type], model_path)
                joblib.dump(self.scalers[model_type], scaler_path)
                
                with open(metadata_path, 'w') as f:
                    json.dump(self.model_metadata.get(model_type, {}), f, indent=2)
                
                with open(features_path, 'w') as f:
                    json.dump(self.feature_columns.get(model_type, []), f, indent=2)
    
    def load_models(self):
        """Load trained models from disk."""
        for model_type in ['memory', 'time', 'cpu']:
            model_path = self.model_dir / f"{model_type}_model.joblib"
            scaler_path = self.model_dir / f"{model_type}_scaler.joblib"
            metadata_path = self.model_dir / f"{model_type}_metadata.json"
            features_path = self.model_dir / f"{model_type}_features.json"
            
            if model_path.exists():
                self.models[model_type] = joblib.load(model_path)
                self.scalers[model_type] = joblib.load(scaler_path)
                
                with open(metadata_path, 'r') as f:
                    self.model_metadata[model_type] = json.load(f)
                
                with open(features_path, 'r') as f:
                    self.feature_columns[model_type] = json.load(f)
                
                print(f"✓ Loaded {model_type} model")
            else:
                print(f"⚠ No {model_type} model found")


def train_all_models(df: pd.DataFrame, model_dir: str = "/code/models") -> Dict:
    """
    Train all resource prediction models.
    
    Args:
        df: DataFrame with features and targets
        model_dir: Directory to save models
    
    Returns:
        Dictionary with training results for all models
    """
    
    from ml.features import prepare_training_data
    
    predictor = ResourcePredictor(model_dir=model_dir)
    results = {}
    
    # Train memory model
    print("Training memory prediction model...")
    X_mem, y_mem, features_mem = prepare_training_data(df, 'target_memory_mb')
    if len(X_mem) > 10:
        metrics_mem = predictor.train_model(X_mem, y_mem, 'memory')
        results['memory'] = metrics_mem
        print(f"  ✓ Memory model R²: {metrics_mem.get('test_r2', 0):.3f}")
    else:
        results['memory'] = {'error': 'Insufficient data', 'success': False}
        print(f"  ✗ Insufficient data for memory model")
    
    # Train time model
    print("Training time prediction model...")
    X_time, y_time, features_time = prepare_training_data(df, 'target_duration_sec')
    if len(X_time) > 10:
        metrics_time = predictor.train_model(X_time, y_time, 'time')
        results['time'] = metrics_time
        print(f"  ✓ Time model R²: {metrics_time.get('test_r2', 0):.3f}")
    else:
        results['time'] = {'error': 'Insufficient data', 'success': False}
        print(f"  ✗ Insufficient data for time model")
    
    # Train CPU model
    print("Training CPU prediction model...")
    X_cpu, y_cpu, features_cpu = prepare_training_data(df, 'target_cpus')
    if len(X_cpu) > 10:
        metrics_cpu = predictor.train_model(X_cpu, y_cpu, 'cpu')
        results['cpu'] = metrics_cpu
        print(f"  ✓ CPU model R²: {metrics_cpu.get('test_r2', 0):.3f}")
    else:
        results['cpu'] = {'error': 'Insufficient data', 'success': False}
        print(f"  ✗ Insufficient data for CPU model")
    
    # Save models
    predictor.save_models()
    print(f"✓ Models saved to {model_dir}")
    
    return results
