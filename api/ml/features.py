"""
Feature engineering for ML-based resource prediction.
Extracts features from historical workflow execution data.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from sqlmodel import Session, select
from datetime import datetime, timezone


def extract_process_features(session: Session, institute_id: Optional[str] = None) -> pd.DataFrame:
    """
    Extract features from process execution data for ML training.
    
    Features include:
    - Process name (one-hot encoded)
    - Input/output file counts (from BCO provenance)
    - Requested resources (CPUs, memory, time, disk)
    - Actual usage (peak RSS, peak VMEM, CPU%, memory%)
    - I/O metrics (read/write chars)
    - CO2/energy data (if available)
    - Hardware info (CPU model)
    - Institute ID
    """
    
    # Build query for process executions
    query = """
    SELECT 
        p.id,
        p.process_name,
        p.module_name,
        p.container_name,
        p.cpus_requested,
        p.time_requested,
        p.storage_requested,
        p.memory_requested,
        p.realtime,
        p.percent_cpu,
        p.percent_memory,
        p.peak_rss,
        p.peak_vmem,
        p.read_char,
        p.write_char,
        p.duration,
        p.disk_usage_mb,
        p.read_bytes,
        p.write_bytes,
        p.peak_vmem_mb,
        p.peak_rss_mb,
        p.institute_id,
        w.run_name,
        w.nextflow_version,
        c.energy_consumption_mwh,
        c.co2e_mg,
        c.cpu_model,
        c.powerdraw_cpu_w
    FROM processexecution p
    LEFT JOIN workflowexecution w ON p.workflow_execution_id = w.id
    LEFT JOIN co2footprint c ON p.id = c.process_execution_id
    """
    
    if institute_id:
        query += f" WHERE p.institute_id = '{institute_id}'"
    
    # Execute query
    df = pd.read_sql(query, session.bind)
    
    if df.empty:
        return df
    
    # ==================== Feature Engineering ====================
    
    # 1. Process name features
    # Extract base process name (last component)
    df['process_base'] = df['process_name'].apply(
        lambda x: x.split(':')[-1].split()[0] if isinstance(x, str) else 'unknown'
    )
    
    # Extract module name from full process name
    df['has_module'] = df['process_name'].apply(
        lambda x: 1 if ':' in str(x) else 0
    )
    
    # 2. Resource ratio features
    df['cpu_utilization'] = df['percent_cpu'] / 100.0
    df['memory_utilization'] = df['percent_memory'] / 100.0
    
    # Memory efficiency (actual vs requested)
    df['memory_requested_mb'] = df['memory_requested'].apply(
        lambda x: x / 1024 if pd.notna(x) and x > 1000 else x
    )
    df['memory_efficiency'] = df['peak_rss'] / df['memory_requested_mb'].replace(0, np.nan)
    
    # Time efficiency
    df['time_efficiency'] = df['duration'] / df['time_requested'].replace(0, np.nan)
    
    # 3. I/O intensity (character I/O from trace)
    df['io_total'] = df['read_char'] + df['write_char']
    df['io_ratio'] = df['read_char'] / (df['write_char'] + 1)
    
    # 3b. Disk I/O intensity (from work directory scanning)
    df['disk_io_total'] = df['read_bytes'].fillna(0) + df['write_bytes'].fillna(0)
    df['disk_io_ratio'] = df['read_bytes'].fillna(0) / (df['write_bytes'].fillna(0) + 1)
    df['disk_intensity'] = df['disk_usage_mb'].fillna(0)
    
    # 4. CPU-Memory correlation
    df['cpu_mem_product'] = df['percent_cpu'] * df['peak_rss']
    
    # 5. Energy efficiency (if CO2 data available)
    if 'energy_consumption_mwh' in df.columns:
        df['energy_per_sec'] = df['energy_consumption_mwh'] / df['duration'].replace(0, np.nan)
        df['co2_per_mb'] = df['co2e_mg'] / df['peak_rss'].replace(0, np.nan)
    
    # 6. Institute encoding
    if 'institute_id' in df.columns:
        institute_mapping = {inst: idx for idx, inst in enumerate(df['institute_id'].dropna().unique())}
        df['institute_encoded'] = df['institute_id'].map(institute_mapping).fillna(-1).astype(float)
    
    # 7. CPU model encoding
    if 'cpu_model' in df.columns:
        cpu_mapping = {cpu: idx for idx, cpu in enumerate(df['cpu_model'].dropna().unique())}
        df['cpu_encoded'] = df['cpu_model'].map(cpu_mapping).fillna(-1).astype(float)
    
    # ==================== Target Variables ====================
    
    # Memory prediction target (MB)
    df['target_memory_mb'] = df['peak_rss']
    
    # Time prediction target (seconds)
    df['target_duration_sec'] = df['duration']
    
    # CPU prediction target (number of cores)
    # Priority: 1) Use explicit cpus_requested, 2) Estimate from percent_cpu
    # For percent_cpu: if > 100%, tool is using multiple cores
    # Estimate: cores = percent_cpu / 100, but cap at reasonable values
    def estimate_cpus(row):
        if pd.notna(row['cpus_requested']) and row['cpus_requested'] > 0:
            return row['cpus_requested']
        elif pd.notna(row['percent_cpu']) and row['percent_cpu'] > 0:
            # If percent_cpu > 100, likely multi-threaded
            # Use ceiling division but cap at 16 for wild estimates
            estimated = int(np.ceil(row['percent_cpu'] / 100))
            return min(16, max(1, estimated))
        else:
            return 1
    
    df['target_cpus'] = df.apply(estimate_cpus, axis=1)
    
    return df


def prepare_training_data(df: pd.DataFrame, target: str = 'target_memory_mb') -> tuple:
    """
    Prepare data for ML training.
    
    Returns:
        X: Feature matrix
        y: Target variable
        feature_names: List of feature column names
    """
    
    # Select features for training
    feature_columns = [
        'process_base',
        'has_module',
        'cpu_utilization',
        'memory_utilization',
        'io_total',
        'io_ratio',
        'disk_io_total',
        'disk_io_ratio',
        'disk_intensity',
        'cpu_mem_product',
        'institute_encoded',
        'cpu_encoded',
    ]
    
    # Add CO2 features if available
    if 'energy_per_sec' in df.columns:
        feature_columns.append('energy_per_sec')
    
    if 'co2_per_mb' in df.columns:
        feature_columns.append('co2_per_mb')
    
    # Filter to rows with valid target
    df_clean = df[df[target].notna()].copy()
    
    # Define categorical columns
    categorical_cols = ['process_base']
    
    # Convert feature columns to numeric (EXPLICIT selection)
    for col in feature_columns:
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0)
        else:
            # Feature not available, create as zeros
            df_clean[col] = 0
    
    # One-hot encoding for categorical features
    df_encoded = pd.get_dummies(df_clean, columns=categorical_cols, drop_first=True)
    
    # Get final feature columns (from our explicit list + one-hot encoded categoricals)
    feature_cols_final = [c for c in df_encoded.columns if c in feature_columns or c.startswith('process_base_')]
    
    # Ensure all features are numeric
    X = df_encoded[feature_cols_final].apply(pd.to_numeric, errors='coerce').fillna(0)
    X = X.replace([np.inf, -np.inf], 0)
    y = pd.to_numeric(df_clean[target], errors='coerce').fillna(0)
    
    return X, y, feature_cols_final


def get_feature_statistics(df: pd.DataFrame) -> Dict:
    """
    Calculate statistics for feature understanding and model interpretability.
    """
    stats = {}
    
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    
    for col in numeric_cols:
        if col in ['target_memory_mb', 'target_duration_sec', 'target_cpus', 
                   'peak_rss', 'peak_vmem', 'duration', 'percent_cpu']:
            stats[col] = {
                'mean': df[col].mean(),
                'std': df[col].std(),
                'min': df[col].min(),
                'max': df[col].max(),
                'median': df[col].median(),
                'p95': df[col].quantile(0.95),
                'p99': df[col].quantile(0.99),
                'count': df[col].count(),
            }
    
    # Process name distribution
    if 'process_base' in df.columns:
        stats['process_distribution'] = df['process_base'].value_counts().head(20).to_dict()
    
    # Institute distribution
    if 'institute_id' in df.columns:
        stats['institute_distribution'] = df['institute_id'].value_counts().to_dict()
    
    return stats
