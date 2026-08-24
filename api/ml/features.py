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
    # Extract base process name (last component), stripping test condition suffixes
    def clean_module_name(name):
        if not isinstance(name, str):
            return 'unknown'
        # Get last component after colon
        module = name.split(':')[-1].split()[0]
        # Remove numeric suffixes
        if module.endswith('_1') or module.endswith('_2'):
            module = module[:-2]
        # Remove test condition suffixes (_QUERY, _TRUTH, _FP, _TP, _TEST, _EVAL)
        test_suffixes = ['_QUERY', '_TRUTH', '_FP', '_TP', '_TEST', '_EVAL']
        for suffix in test_suffixes:
            if module.endswith(suffix):
                module = module[:-len(suffix)]
                break
        return module
    
    df['process_base'] = df['process_name'].apply(clean_module_name)
    
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
    
    # MEMORY TARGET STRATEGY:
    # Use peak RSS (actual memory used)
    # Model will predict P95 to avoid OOM kills
    # Under-allocation = job failure (catastrophic)
    # Over-allocation = wasted resources (acceptable)
    df['target_memory_mb'] = df['peak_rss']
    
    # TIME TARGET STRATEGY:
    # Use actual duration, BUT model must be EXTREMELY conservative
    # Time is a KILL LIMIT - exceeding it kills the job
    # Model will predict P99 (not P95) for maximum safety
    # Minimum 1 hour (3600s) enforced at prediction time
    df['target_duration_sec'] = df['duration']
    
    # CPU prediction target (number of cores)
    # Priority: 1) Use explicit cpus_requested, 2) Estimate from percent_cpu
    # CPU TARGET STRATEGY:
    # 
    # CRITICAL UNDERSTANDING: percent_cpu from Nextflow trace = (CPU_time / realtime) * 100
    # - 100% = 1 core fully utilized for entire runtime
    # - 400% = 4 cores fully utilized (or equivalent parallel work)
    # - 50% = 1 core at 50% utilization (idle half the time)
    #
    # Features and their meanings:
    # - cpus_requested: What user asked for (may be wrong)
    # - percent_cpu: Actual parallelism achieved (ground truth)
    # - duration: How long it ran
    # - peak_rss: Memory pressure (may affect CPU if swapping)
    # - disk_usage_mb: Data size (larger data may need more parallelism)
    # - read_bytes/write_bytes: I/O intensity (I/O bound tools show low CPU%)
    #
    # Target: Learn optimal CPU allocation that achieves 70-90% per-core utilization
    def estimate_cpus(row):
        percent_cpu = row['percent_cpu'] if pd.notna(row['percent_cpu']) else 0
        cpus_requested = row['cpus_requested'] if pd.notna(row['cpus_requested']) else 0
        duration = row['duration'] if pd.notna(row['duration']) else 0
        disk_usage = row.get('disk_usage_mb', 0) or 0
        io_total = (row.get('read_bytes', 0) or 0) + (row.get('write_bytes', 0) or 0)
        
        # Calculate actual cores utilized (percent_cpu / 100)
        # This is the ground truth: how many cores were actually busy
        actual_cores_used = percent_cpu / 100.0
        
        if cpus_requested > 0:
            # Calculate per-core utilization
            per_core_util = percent_cpu / cpus_requested
            
            # Decision logic based on per-core utilization:
            if per_core_util < 30:
                # Severely over-allocated (e.g., requested 8, used 200% = 2 cores)
                # Tool doesn't need that many cores
                optimal_cpus = max(1, int(np.ceil(actual_cores_used)))
            elif per_core_util < 70:
                # Moderately over-allocated (e.g., requested 4, used 200% = 2 cores)
                # Can reduce but keep some headroom
                optimal_cpus = max(1, int(np.ceil(actual_cores_used * 1.2)))
            elif per_core_util > 95:
                # Under-allocated or perfect (e.g., requested 2, used 190% = 1.9 cores)
                # Add 1 core for headroom
                optimal_cpus = max(1, int(np.ceil(actual_cores_used)) + 1)
            else:
                # Optimal range 70-95% (e.g., requested 4, used 320% = 3.2 cores)
                # Keep as-is or round up slightly
                optimal_cpus = max(1, int(np.ceil(actual_cores_used)))
            
            return min(16, optimal_cpus)
        elif percent_cpu > 0:
            # No requested data, use actual usage rounded up
            return min(16, max(1, int(np.ceil(actual_cores_used))))
        elif cpus_requested > 0:
            # Fallback to requested
            return cpus_requested
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
