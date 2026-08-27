"""
ML models for resource prediction - PER-PROCESS MODELS.

Each process gets its own model trained on its historical data only.
Processes with <10 samples use the global fallback model.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler
import joblib
import json
import os
from pathlib import Path
from typing import Dict, Tuple, Optional, List
from datetime import datetime, timezone


class ResourcePredictor:
    """
    Per-process ML resource predictor.
    
    Structure:
    - self.models[process_name][resource_type] = model
    - self.models['_fallback'][resource_type] = global fallback model
    """
    
    def __init__(self, model_dir: str = "/code/models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Per-process models: {process_name: {resource_type: model}}
        self.models: Dict[str, Dict[str, Optional[GradientBoostingRegressor]]] = {}
        
        # Per-process scalers
        self.scalers: Dict[str, Dict[str, Optional[StandardScaler]]] = {}
        
        # Feature columns per process per resource
        self.feature_columns: Dict[str, Dict[str, List[str]]] = {}
        
        # Model metadata per process
        self.model_metadata: Dict[str, Dict[str, Dict]] = {}
    
    def train_process_model(
        self,
        process_name: str,
        X: pd.DataFrame,
        y: pd.Series,
        resource_type: str,
        model_path: str
    ) -> Dict:
        """
        Train a model for a specific process and resource type.
        
        Args:
            process_name: Normalized process name (e.g., "BCFTOOLS_FILTER")
            X: Feature matrix
            y: Target variable
            resource_type: 'memory', 'time', or 'cpu'
            model_path: Path to save model
        
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
        
        # Train model
        model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42
        )
        model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred_train = model.predict(X_train_scaled)
        y_pred_test = model.predict(X_test_scaled)
        
        # Cross-validation
        cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=5, scoring='r2')
        
        # Calculate metrics
        metrics = {
            'process_name': process_name,
            'resource_type': resource_type,
            'training_samples': len(X_train),
            'test_samples': len(X_test),
            'train_rmse': float(np.sqrt(mean_squared_error(y_train, y_pred_train))),
            'train_mae': float(mean_absolute_error(y_train, y_pred_train)),
            'train_r2': float(r2_score(y_train, y_pred_train)),
            'test_rmse': float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
            'test_mae': float(mean_absolute_error(y_test, y_pred_test)),
            'test_r2': float(r2_score(y_test, y_pred_test)),
            'cv_r2_mean': float(cv_scores.mean()),
            'cv_r2_std': float(cv_scores.std()),
            'feature_importance': dict(zip(
                X.columns,
                model.feature_importances_.tolist()
            )),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'success': True,
        }
        
        # Save model and scaler
        joblib.dump(model, model_path)
        joblib.dump(scaler, model_path.replace('.pkl', '_scaler.pkl'))
        
        return metrics
    
    def train_all_process_models(
        self,
        df: pd.DataFrame,
        institute_id: Optional[str] = None
    ) -> Dict:
        """
        Train per-process models for all processes in the dataset.
        
        Args:
            df: DataFrame with all process data
            institute_id: Optional filter by institute
        
        Returns:
            Dictionary with training results for all processes
        """
        from .features import prepare_training_data
        
        results = {
            'per_process': {},
            'fallback': {},
            'summary': {
                'total_processes': 0,
                'processes_with_models': 0,
                'processes_using_fallback': 0,
            }
        }
        
        # Filter by institute if specified
        if institute_id:
            df = df[df['institute_id'] == institute_id].copy()
        
        # Group by normalized process name
        grouped = df.groupby('module_name')
        results['summary']['total_processes'] = len(grouped)
        
        # Train per-process models
        for process_name, group_df in grouped:
            if len(group_df) < 10:
                # Not enough samples - will use fallback
                results['per_process'][process_name] = {
                    'status': 'fallback',
                    'samples': len(group_df),
                    'reason': 'Insufficient samples (<10)'
                }
                results['summary']['processes_using_fallback'] += 1
                continue
            
            results['per_process'][process_name] = {
                'status': 'trained',
                'samples': len(group_df),
                'models': {}
            }
            
            # Train models for each resource type
            for resource_type, target_col in [
                ('memory', 'target_memory_mb'),
                ('time', 'target_duration_sec'),
                ('cpu', 'target_cpus')
            ]:
                try:
                    X, y, feature_cols = prepare_training_data(group_df, target_col)
                    
                    if len(X) < 10:
                        continue
                    
                    model_path = str(self.model_dir / f"{process_name}_{resource_type}.pkl")
                    metrics = self.train_process_model(
                        process_name, X, y, resource_type, model_path
                    )
                    
                    if metrics.get('success'):
                        # Store feature columns for this process/resource
                        if process_name not in self.feature_columns:
                            self.feature_columns[process_name] = {}
                        self.feature_columns[process_name][resource_type] = feature_cols
                        
                        results['per_process'][process_name]['models'][resource_type] = metrics
                        results['summary']['processes_with_models'] += 1
                        
                except Exception as e:
                    results['per_process'][process_name]['models'][resource_type] = {
                        'error': str(e),
                        'success': False
                    }
        
        # Train global fallback model on ALL data
        print("Training global fallback model on all data...")
        for resource_type, target_col in [
            ('memory', 'target_memory_mb'),
            ('time', 'target_duration_sec'),
            ('cpu', 'target_cpus')
        ]:
            try:
                X, y, feature_cols = prepare_training_data(df, target_col)
                
                if len(X) >= 10:
                    model_path = str(self.model_dir / f"_fallback_{resource_type}.pkl")
                    metrics = self.train_process_model(
                        '_fallback', X, y, resource_type, model_path
                    )
                    
                    if metrics.get('success'):
                        self.feature_columns['_fallback'][resource_type] = feature_cols
                        results['fallback'][resource_type] = metrics
                        
            except Exception as e:
                results['fallback'][resource_type] = {
                    'error': str(e),
                    'success': False
                }
        
        return results
    
    def load_process_model(
        self,
        process_name: str,
        resource_type: str
    ) -> Tuple[Optional[GradientBoostingRegressor], Optional[StandardScaler], Optional[List[str]]]:
        """
        Load a model for a specific process and resource type.
        
        Returns:
            Tuple of (model, scaler, feature_columns) or (None, None, None) if not found
        """
        # Check if already loaded
        if process_name in self.models and resource_type in self.models[process_name]:
            return (
                self.models[process_name][resource_type],
                self.scalers[process_name][resource_type],
                self.feature_columns.get(process_name, {}).get(resource_type)
            )
        
        # Load from disk
        model_path = self.model_dir / f"{process_name}_{resource_type}.pkl"
        scaler_path = self.model_dir / f"{process_name}_{resource_type}_scaler.pkl"
        
        if not model_path.exists() or not scaler_path.exists():
            return None, None, None
        
        try:
            model = joblib.load(model_path)
            scaler = joblib.load(scaler_path)
            
            # Load feature columns from metadata file if exists
            feature_cols = None
            meta_path = self.model_dir / f"{process_name}_{resource_type}_meta.json"
            if meta_path.exists():
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    feature_cols = meta.get('feature_columns')
            
            # Cache in memory
            if process_name not in self.models:
                self.models[process_name] = {}
                self.scalers[process_name] = {}
            
            self.models[process_name][resource_type] = model
            self.scalers[process_name][resource_type] = scaler
            if feature_cols:
                self.feature_columns[process_name][resource_type] = feature_cols
            
            return model, scaler, feature_cols
            
        except Exception as e:
            print(f"Error loading model {model_path}: {e}")
            return None, None, None
    
    def predict_for_process(
        self,
        process_name: str,
        features: Dict,
        resource_type: str
    ) -> Dict:
        """
        Predict resource requirements for a specific process.
        
        Tries per-process model first, falls back to global model if not available.
        
        Args:
            process_name: Normalized process name
            features: Feature dictionary
            resource_type: 'memory', 'time', or 'cpu'
        
        Returns:
            Prediction result dictionary
        """
        # Try per-process model first
        model, scaler, feature_cols = self.load_process_model(process_name, resource_type)
        is_fallback = False
        
        # Fall back to global model if per-process not available
        if model is None:
            model, scaler, feature_cols = self.load_process_model('_fallback', resource_type)
            is_fallback = True
        
        if model is None or scaler is None:
            return {
                'error': f'No model available for {process_name} {resource_type}',
                'success': False,
                'is_fallback': False
            }
        
        # Convert features to DataFrame
        feature_df = pd.DataFrame([features])
        
        # Ensure all expected columns are present
        if feature_cols:
            for col in feature_cols:
                if col not in feature_df.columns:
                    feature_df[col] = 0
            feature_df = feature_df[feature_cols]
        
        # Scale features
        feature_scaled = scaler.transform(feature_df)
        
        # Predict
        prediction = model.predict(feature_scaled)[0]
        
        # Calculate safety margin (15% for per-process, 30% for fallback)
        safety_margin = 1.15 if not is_fallback else 1.30
        
        result = {
            'prediction': float(prediction),
            'prediction_with_safety': float(prediction * safety_margin),
            'safety_margin': safety_margin,
            'is_fallback_model': is_fallback,
            'process_name': process_name,
            'resource_type': resource_type,
            'success': True
        }
        
        return result
