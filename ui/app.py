import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import requests
import os
import re
import json

st.set_page_config(page_title="Nextflow Resource Monitoring", layout="wide")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost")
env_api_key = os.getenv("API_KEY", "")

with st.sidebar:
    st.subheader("Authentication")
    API_KEY = st.text_input("API Key", value=env_api_key, type="password")
    
    st.divider()
    
    st.subheader("Navigation")
    page = st.radio(
        "Go to",
        ["Dashboard", "ML Training", "Optimizations", "Model Performance"],
        label_visibility="collapsed"
    )

def render_resource_charts(df: pd.DataFrame):
    st.title("📊 Dashboard - Real Workflow Metrics")
    st.write("View **actual historical execution data** from your submitted workflows.")
    
    # ============================================
    # DETAILED DATA TABLE - ALL RUNS (TOP - FIRST THING USER SEES)
    # ============================================
    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        # Sanitize process names
        display_df = df.copy()
        if 'process_name' in display_df.columns:
            display_df['process_name'] = display_df['process_name'].apply(
                lambda x: re.sub(r'\s*\(.*\)', '', str(x)) if isinstance(x, str) else str(x)
            )
        
        # Select and order columns for display
        display_columns = [
            'process_name', 'workflow_name', 'institute_id', 'duration',
            'peak_rss', 'peak_vmem', 'percent_cpu', 'cpus_requested',
            'memory_requested', 'time_requested', 'disk_usage_mb',
            'read_bytes', 'write_bytes', 'start_time'
        ]
        available_columns = [col for col in display_columns if col in display_df.columns]
        
        st.subheader("📋 Detailed Execution Data (All Runs)")
        st.dataframe(
            display_df[available_columns],
            use_container_width=True,
            height=500
        )
        st.info(f"Total runs: {len(display_df)}")
    else:
        st.info("No detailed data available")
    
    st.divider()
    
    # ============================================
    # SUMMARY STATISTICS
    # ============================================
    st.subheader("📈 Summary Statistics by Process")
    
    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        display_df = df.copy()
        if 'process_name' in display_df.columns:
            display_df['process_name'] = display_df['process_name'].apply(
                lambda x: re.sub(r'\s*\(.*\)', '', str(x)) if isinstance(x, str) else str(x)
            )
        
        display_df['short_name'] = display_df['process_name'].apply(
            lambda x: x.split(':')[-1] if isinstance(x, str) else str(x)
        )
        
        numeric_metrics = {
            'duration': ('Duration', 's'),
            'peak_rss': ('Memory Used', 'MB'),
            'percent_cpu': ('CPU Utilization', '%'),
            'disk_usage_mb': ('Disk Usage', 'MB'),
            'cpus_requested': ('CPUs Requested', 'cores'),
            'memory_requested': ('Memory Requested', 'MB'),
            'time_requested': ('Time Requested', 's')
        }
        
        for metric, (label, unit) in numeric_metrics.items():
            if metric in display_df.columns and not display_df[metric].isna().all():
                with st.expander(f"{label} ({unit})"):
                    stats_df = display_df.groupby('short_name')[metric].agg([
                        'count', 'mean', 'std', 'min', 'median', 'max'
                    ]).round(2)
                    stats_df.columns = ['Runs', 'Average', 'Std Dev', 'Min', 'Median', 'Max']
                    stats_df = stats_df.sort_values('Average', ascending=False)
                    st.dataframe(stats_df, use_container_width=True)
    
    st.divider()
    
    # ============================================
    # VISUALIZATIONS
    # ============================================
    st.subheader("📉 Process Resource Visualizations")
    
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.warning("No data found to display.")
        return
        
    if 'process_name' not in df.columns or 'duration' not in df.columns:
        st.error(f"Missing columns! Available columns: {list(df.columns)}")
        return

    work_df = df.copy()
    
    # PRIVACY FIX: Sanitize process names everywhere
    work_df['process_name'] = work_df['process_name'].apply(
        lambda x: re.sub(r'\s*\(.*\)', '', str(x)) if isinstance(x, str) else str(x)
    )
    
    work_df['short_name'] = work_df['process_name'].apply(
        lambda x: x.split(':')[-1] if isinstance(x, str) else str(x)
    )
    
    if 'start_time' in work_df.columns:
        work_df['start_time'] = pd.to_datetime(work_df['start_time'], unit='s', errors='coerce')

    all_processes = work_df['short_name'].unique().tolist()
    
    if not all_processes:
        st.info("No process names found.")
        return

    selected_processes = st.multiselect(
        "Select Processes to Display", 
        options=all_processes, 
        default=all_processes[:10] if len(all_processes) >= 10 else all_processes
    )
    
    if not selected_processes:
        st.info("Please select at least one process.")
        return

    filtered_df = work_df[work_df['short_name'].isin(selected_processes)]
    
    if filtered_df.empty:
        st.info("No data matches the selected filters.")
        return

    numeric_cols = ['duration', 'peak_rss', 'percent_cpu', 'realtime', 'peak_vmem', 
                    'storage_requested', 'time_requested', 'disk_usage_mb', 
                    'read_bytes', 'write_bytes', 'peak_vmem_mb', 'peak_rss_mb']
    available_numeric = [col for col in numeric_cols if col in filtered_df.columns]
    
    avg_df = filtered_df.groupby('short_name')[available_numeric].mean().reset_index()

    metric_labels = {
        'duration': 'Average Duration (seconds)',
        'peak_rss': 'Average Peak RSS (MB)',
        'percent_cpu': 'Average CPU Percentage (%)',
        'realtime': 'Average Realtime (seconds)',
        'peak_vmem': 'Average Peak Virtual Memory (MB)',
        'storage_requested': 'Average Storage Requested (MB)',
        'time_requested': 'Average Time Requested (seconds)',
        'disk_usage_mb': 'Average Disk Usage (MB)',
        'read_bytes': 'Average Read Bytes',
        'write_bytes': 'Average Write Bytes',
        'peak_vmem_mb': 'Average Peak VMEM (MB)',
        'peak_rss_mb': 'Average Peak RSS (MB)'
    }

    selected_metric = st.selectbox(
        "Select Metric to Visualize",
        options=available_numeric,
        format_func=lambda x: metric_labels.get(x, x)
    )

    fig = px.bar(
        avg_df, 
        x='short_name', 
        y=selected_metric,
        title=f"Average {metric_labels.get(selected_metric, selected_metric)} by Process",
        labels={'short_name': 'Process', selected_metric: metric_labels.get(selected_metric, selected_metric)}
    )
    fig.update_layout(xaxis_tickangle=-45, margin=dict(b=100))
    st.plotly_chart(fig, use_container_width=True)
    
    # Enhanced CPU Visualization
    if 'percent_cpu' in filtered_df.columns and not filtered_df['percent_cpu'].isna().all():
        st.subheader("CPU Utilization Distribution")
        
        cpu_data = filtered_df[['short_name', 'percent_cpu']].dropna()
        if not cpu_data.empty:
            fig_cpu = px.box(
                cpu_data,
                x='short_name',
                y='percent_cpu',
                title='CPU Utilization Distribution by Process (shows variability and outliers)',
                labels={'short_name': 'Process', 'percent_cpu': 'CPU Utilization (%)'}
            )
            fig_cpu.update_layout(xaxis_tickangle=-45, margin=dict(b=100))
            st.plotly_chart(fig_cpu, use_container_width=True)
            
            # CPU utilization histogram
            fig_hist = px.histogram(
                filtered_df,
                x='percent_cpu',
                color='short_name',
                title='CPU Utilization Histogram',
                labels={'percent_cpu': 'CPU Utilization (%)', 'count': 'Count'}
            )
            fig_hist.update_layout(margin=dict(b=100))
            st.plotly_chart(fig_hist, use_container_width=True)
    
    # Disk Usage Visualization
    disk_cols = [col for col in ['disk_usage_mb', 'read_bytes', 'write_bytes'] if col in filtered_df.columns]
    if disk_cols and not all(filtered_df[col].isna().all() for col in disk_cols):
        st.subheader("Disk I/O & Storage Metrics")
        
        # Disk usage bar chart
        if 'disk_usage_mb' in filtered_df.columns and not filtered_df['disk_usage_mb'].isna().all():
            disk_df = filtered_df[['short_name', 'disk_usage_mb']].dropna()
            if not disk_df.empty:
                fig_disk = px.bar(
                    disk_df.groupby('short_name')['disk_usage_mb'].mean().reset_index(),
                    x='short_name',
                    y='disk_usage_mb',
                    title='Average Disk Usage by Process (MB)',
                    labels={'short_name': 'Process', 'disk_usage_mb': 'Disk Usage (MB)'}
                )
                fig_disk.update_layout(xaxis_tickangle=-45, margin=dict(b=100))
                st.plotly_chart(fig_disk, use_container_width=True)
        
        # Read/Write bytes comparison
        if 'read_bytes' in filtered_df.columns and 'write_bytes' in filtered_df.columns:
            io_df = filtered_df[['short_name', 'read_bytes', 'write_bytes']].dropna()
            if not io_df.empty:
                io_avg = io_df.groupby('short_name')[['read_bytes', 'write_bytes']].mean().reset_index()
                io_melted = io_avg.melt(id_vars=['short_name'], value_vars=['read_bytes', 'write_bytes'],
                                       var_name='IO Type', value_name='Bytes')
                
                fig_io = px.bar(
                    io_melted,
                    x='short_name',
                    y='Bytes',
                    color='IO Type',
                    title='Average I/O Bytes by Process',
                    barmode='group',
                    labels={'short_name': 'Process', 'IO Type': 'Operation Type'}
                )
                fig_io.update_layout(xaxis_tickangle=-45, margin=dict(b=100))
                st.plotly_chart(fig_io, use_container_width=True)


@st.cache_data
def fetch_process_data(api_key_val):
    headers = {
        "Authorization": f"Bearer {api_key_val}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(f"{API_BASE_URL}/processes/", headers=headers)
        if response.status_code == 200:
            data = response.json()
            return pd.DataFrame(data)
        else:
            st.error(f"API Error - Status Code: {response.status_code}")
            st.text(response.text)
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Connection failed: {e}")
        return pd.DataFrame()

def render_ml_training():
    st.title("🤖 ML Training - Build Prediction Models")
    st.write("""
    **Step 2: Train ML Models**
    
    After reviewing your historical data in the Dashboard, train ML models to learn resource usage patterns. 
    These models will enable predictions for small, medium, and large dataset scenarios.
    """)
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Training Configuration")
        institute_id = st.text_input("Institute ID", value="DKFZ", help="Filter data by institute for training")
        
        if st.button("Start Training", type="primary", use_container_width=True):
            with st.spinner("Training models... This may take a minute."):
                headers = {
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                }
                try:
                    response = requests.post(
                        f"{API_BASE_URL}/ml/train",
                        headers=headers,
                        json={"institute_id": institute_id} if institute_id else {}
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        st.session_state['training_result'] = result
                        st.success(f"Training completed! {result.get('message', '')}")
                    else:
                        st.error(f"Training failed: {response.text}")
                except Exception as e:
                    st.error(f"Connection failed: {e}")
    
    with col2:
        st.subheader("Training Results")
        if 'training_result' in st.session_state:
            result = st.session_state['training_result']
            
            if result.get('success'):
                st.metric("Training Samples", result.get('training_samples', 0))
                
                model_results = result.get('model_results', {})
                
                if model_results:
                    for model_type, metrics in model_results.items():
                        if isinstance(metrics, dict):
                            r2 = metrics.get('test_r2', 0)
                            rmse = metrics.get('test_rmse', 0)
                            st.write(f"**{model_type.title()} Model**")
                            st.write(f"  - Test R²: {r2:.4f}")
                            st.write(f"  - Test RMSE: {rmse:.4f}")
                            st.write(f"  - CV R²: {metrics.get('cv_r2_mean', 0):.4f}")
                
                stats = result.get('feature_statistics', {})
                if stats:
                    st.write("**Feature Statistics:**")
                    for metric, values in list(stats.items())[:3]:
                        if isinstance(values, dict) and 'mean' in values:
                            st.write(f"- {metric}: mean={values.get('mean', 0):.1f}, range=[{values.get('min', 0):.1f}, {values.get('max', 0):.1f}]")
            else:
                st.error(f"Training failed: {result.get('error', 'Unknown error')}")
        else:
            st.info("No training results yet. Click 'Start Training' to train models.")

@st.cache_data(ttl=300)
def fetch_processes(api_key_val, institute_id=None):
    """Fetch available module names from the API (without instance suffix)."""
    headers = {
        "Authorization": f"Bearer {api_key_val}",
        "Content-Type": "application/json"
    }
    try:
        url = f"{API_BASE_URL}/ml/processes"
        if institute_id:
            url += f"?institute_id={institute_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get('processes', [])
        else:
            return []
    except Exception:
        return []


@st.cache_data(ttl=300)
def fetch_all_optimizations(api_key_val, institute_id=None):
    """Fetch all optimization recommendations for ALL processes with S/M/L scenarios."""
    headers = {
        "Authorization": f"Bearer {api_key_val}",
        "Content-Type": "application/json"
    }
    try:
        url = f"{API_BASE_URL}/ml/optimizations"
        if institute_id:
            url += f"?institute_id={institute_id}"
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None


def render_optimizations():
    st.title("⚡ Resource Optimizations - ML-Based Configurations")
    st.write("""
    **Get optimized configurations for individual processes OR download all**
    
    ML models predict resources for small, medium, and large dataset sizes.
    Select a process from dropdown to view predictions, or download all configs.
    """)
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return
    
    # Fetch all optimizations
    with st.spinner("Loading ML predictions for all processes..."):
        all_opts = fetch_all_optimizations(API_KEY)
    
    if not all_opts or not all_opts.get('success'):
        st.error("Failed to fetch optimizations. Train models first on ML Training tab.")
        return
    
    optimizations = all_opts.get('optimizations', [])
    
    if not optimizations:
        st.info("No optimizations available. Submit workflow data and train models.")
        return
    
    # ============================================
    # DROPDOWN TO SELECT PROCESS
    # ============================================
    st.subheader("🔍 Select Process to View Predictions")
    
    process_names = [opt.get('module_name', 'unknown') for opt in optimizations]
    selected_process = st.selectbox("Choose a process:", options=process_names)
    
    if selected_process:
        selected_opt = next((opt for opt in optimizations if opt.get('module_name') == selected_process), None)
        
        if selected_opt:
            scenarios = selected_opt.get('scenarios', {})
            samples = selected_opt.get('historical_samples', 0)
            
            st.write(f"**Historical Runs:** {samples}")
            
            col_s, col_m, col_l = st.columns(3)
            
            size_names = ['SMALL', 'MEDIUM', 'LARGE']
            for i, size_name in enumerate(size_names):
                cfg = scenarios.get(size_name, {})
                with [col_s, col_m, col_l][i]:
                    st.write(f"**{size_name} Dataset**")
                    st.write(f"Data Size: ~{cfg.get('disk_size_mb', 0):.1f} MB")
                    st.write(f"**CPUs:** {cfg.get('cpus', 1)}")
                    st.write(f"**Memory:** {cfg.get('memory', 'N/A')}")
                    st.write(f"**Time:** {cfg.get('time', 'N/A')}")
    
    st.divider()
    
    # ============================================
    # DOWNLOAD 3 CONFIG FILES (ONE PER SIZE)
    # ============================================
    st.subheader("📥 Download All Configurations")
    
    import io
    
    # Generate SMALL.config (all processes)
    small_lines = ["// Auto-generated Nextflow configuration", "// SMALL dataset scenario", f"// {len(optimizations)} processes", "process {"]
    for opt in optimizations:
        module = opt.get('module_name', 'unknown')
        scenarios = opt.get('scenarios', {})
        small_cfg = scenarios.get('SMALL', {})
        small_lines.append(f"    withName: '{module}' {{")
        small_lines.append(f"        cpus = {small_cfg.get('cpus', 1)}")
        small_lines.append(f"        memory = '{small_cfg.get('memory', '256 MB')}'")
        small_lines.append(f"        time = '{small_cfg.get('time', '1h')}'")
        small_lines.append("    }")
    small_lines.append("}")
    small_config = "\n".join(small_lines)
    
    # Generate MEDIUM.config (all processes)
    medium_lines = ["// Auto-generated Nextflow configuration", "// MEDIUM dataset scenario", f"// {len(optimizations)} processes", "process {"]
    for opt in optimizations:
        module = opt.get('module_name', 'unknown')
        scenarios = opt.get('scenarios', {})
        medium_cfg = scenarios.get('MEDIUM', {})
        medium_lines.append(f"    withName: '{module}' {{")
        medium_lines.append(f"        cpus = {medium_cfg.get('cpus', 1)}")
        medium_lines.append(f"        memory = '{medium_cfg.get('memory', '256 MB')}'")
        medium_lines.append(f"        time = '{medium_cfg.get('time', '1h')}'")
        medium_lines.append("    }")
    medium_lines.append("}")
    medium_config = "\n".join(medium_lines)
    
    # Generate LARGE.config (all processes)
    large_lines = ["// Auto-generated Nextflow configuration", "// LARGE dataset scenario", f"// {len(optimizations)} processes", "process {"]
    for opt in optimizations:
        module = opt.get('module_name', 'unknown')
        scenarios = opt.get('scenarios', {})
        large_cfg = scenarios.get('LARGE', {})
        large_lines.append(f"    withName: '{module}' {{")
        large_lines.append(f"        cpus = {large_cfg.get('cpus', 1)}")
        large_lines.append(f"        memory = '{large_cfg.get('memory', '256 MB')}'")
        large_lines.append(f"        time = '{large_cfg.get('time', '1h')}'")
        large_lines.append("    }")
    large_lines.append("}")
    large_config = "\n".join(large_lines)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.download_button(
            label="⬇️ SMALL.config",
            data=small_config,
            file_name="small.config",
            mime="text/plain",
            use_container_width=True
        )
    
    with col2:
        st.download_button(
            label="⬇️ MEDIUM.config",
            data=medium_config,
            file_name="medium.config",
            mime="text/plain",
            use_container_width=True
        )
    
    with col3:
        st.download_button(
            label="⬇️ LARGE.config",
            data=large_config,
            file_name="large.config",
            mime="text/plain",
            use_container_width=True
        )
    
    st.info(f"Each file contains ALL {len(optimizations)} processes for that dataset size.")


def render_model_performance():
    st.title("📈 Model Performance - Understanding the Metrics")
    st.write("""
    **Monitor ML model accuracy and understand what the metrics mean**
    
    These metrics tell you how well the trained models can predict resource requirements.
    """)
    
    # Add explanations
    with st.expander("📖 How to Interpret These Metrics"):
        st.write("""
        ### R² (R-Squared / Coefficient of Determination)
        - **What it measures**: How well the model's predictions match actual values
        - **Range**: 0 to 1 (or 0% to 100%)
        - **Interpretation**:
          - **R² > 0.9**: Excellent fit - model explains 90%+ of variance ✅
          - **R² 0.7-0.9**: Good fit - model explains 70-90% of variance 👍
          - **R² 0.5-0.7**: Moderate fit - predictions may be less reliable ⚠️
          - **R² < 0.5**: Poor fit - model needs more training data ❌
        - **Example**: R² = 0.95 means the model explains 95% of the variation in resource usage
        
        ### RMSE (Root Mean Square Error)
        - **What it measures**: Average prediction error (in the same units as the target)
        - **Interpretation**: Lower is better
        - **Example**: RMSE = 100 MB for memory means predictions are off by ~100 MB on average
        
        ### MAE (Mean Absolute Error)
        - **What it measures**: Average absolute prediction error
        - **Interpretation**: Lower is better, less sensitive to outliers than RMSE
        - **Example**: MAE = 50 seconds means predictions are off by ~50 seconds on average
        
        ### CV R² Mean (Cross-Validation R²)
        - **What it measures**: Model performance on unseen data (more reliable than test R²)
        - **Interpretation**: Should be close to test R². Large gap indicates overfitting.
        - **Example**: CV R² = 0.92 means the model generalizes well to new data
        
        ### Feature Importance
        - **What it measures**: Which input features most influence predictions
        - **Interpretation**: Higher = more important
        - **Example**: If 'disk_usage_mb' has highest importance, data size is the main driver of resource usage
        
        ### When to Retrain Models
        - R² drops below 0.7
        - You've submitted many new workflows
        - Predictions consistently differ from actual usage
        - New processes are added that weren't in training data
        """)
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(f"{API_BASE_URL}/ml/models", headers=headers)
        
        if response.status_code == 200:
            models = response.json()
            
            if not models:
                st.info("No trained models found. Train models first on the ML Training page.")
                return
            
            st.subheader("Trained Models Overview")
            
            for model in models:
                model_name = model.get('model_name', 'unknown')
                model_type = model.get('target_process', model.get('model_type', 'unknown'))
                accuracy = json.loads(model.get('accuracy_metrics', '{}'))
                
                # Extract resource type from model name (e.g., "resource_memory_predictor" -> "MEMORY")
                if 'memory' in model_name.lower():
                    resource_type = 'MEMORY'
                elif 'time' in model_name.lower():
                    resource_type = 'TIME'
                elif 'cpu' in model_name.lower():
                    resource_type = 'CPU'
                else:
                    resource_type = model_type.upper() if model_type else 'RESOURCE'
                
                r2 = accuracy.get('test_r2', 0)
                rmse = accuracy.get('test_rmse', 0)
                mae = accuracy.get('test_mae', 0)
                cv_r2 = accuracy.get('cv_r2_mean', 0)
                samples = model.get('training_samples', 0)
                
                with st.expander(f"{resource_type} Prediction Model - Test R²: {r2:.4f}"):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Test R²", f"{r2:.4f}")
                        st.metric("Test RMSE", f"{rmse:.4f}")
                    
                    with col2:
                        st.metric("Test MAE", f"{mae:.4f}")
                        st.metric("CV R²", f"{cv_r2:.4f}")
                    
                    with col3:
                        st.metric("Training Samples", samples)
                        st.metric("Model Type", "GradientBoosting")
                    
                    if model.get('feature_importance'):
                        fi = json.loads(model.get('feature_importance', '{}'))
                        fi_sorted = dict(sorted(fi.items(), key=lambda x: x[1], reverse=True)[:15])
                        fi_df = pd.DataFrame({
                            'Feature': list(fi_sorted.keys()),
                            'Importance': list(fi_sorted.values())
                        })
                        fig = px.bar(fi_df, x='Importance', y='Feature', orientation='h',
                                   title=f"Top 15 Features - {model_type.title()} Model")
                        st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Model Comparison")
            
            if len(models) > 1:
                comparison_data = []
                for model in models:
                    accuracy = json.loads(model.get('accuracy_metrics', '{}'))
                    comparison_data.append({
                        'Model Type': model.get('model_type', 'unknown').title(),
                        'Test R²': accuracy.get('test_r2', 0),
                        'Test RMSE': accuracy.get('test_rmse', 0),
                        'Test MAE': accuracy.get('test_mae', 0),
                        'CV R² Mean': accuracy.get('cv_r2_mean', 0)
                    })
                
                comparison_df = pd.DataFrame(comparison_data)
                
                col1_comp, col2_comp = st.columns(2)
                
                with col1_comp:
                    fig_r2 = px.bar(comparison_df, x='Model Type', y='Test R²',
                                   title='Model Comparison - Test R²',
                                   color='Test R²', color_continuous_scale='Viridis')
                    st.plotly_chart(fig_r2, use_container_width=True)
                
                with col2_comp:
                    fig_rmse = px.bar(comparison_df, x='Model Type', y='Test RMSE',
                                     title='Model Comparison - Test RMSE',
                                     color='Test RMSE', color_continuous_scale='Viridis')
                    st.plotly_chart(fig_rmse, use_container_width=True)
        else:
            st.error(f"Failed to fetch models: {response.text}")
    except Exception as e:
        st.error(f"Connection failed: {e}")

def main():
    st.title("Nextflow Process Resource Monitoring")
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return
    
    if page == "Dashboard":
        df = fetch_process_data(API_KEY)
        render_resource_charts(df)
    elif page == "ML Training":
        render_ml_training()
    elif page == "Optimizations":
        render_optimizations()
    elif page == "Model Performance":
        render_model_performance()

if __name__ == "__main__":
    main()
