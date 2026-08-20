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
        ["Dashboard", "ML Training", "ML Predictions", "Optimization", "Model Performance"],
        label_visibility="collapsed"
    )

def render_resource_charts(df: pd.DataFrame):
    st.subheader("Process Resource Utilization")
    
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.warning("No data found to display.")
        return
        
    if 'process_name' not in df.columns or 'duration' not in df.columns:
        st.error(f"Missing columns! Available columns: {list(df.columns)}")
        return

    work_df = df.copy()
    
    work_df['short_name'] = work_df['process_name'].apply(
        lambda x: re.sub(r'\s*\(.*\)', '', x.split(':')[-1]) if isinstance(x, str) else str(x)
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

    numeric_cols = ['duration', 'peak_rss', 'percent_cpu', 'realtime', 'peak_vmem', 'storage_requested', 'time_requested']
    available_numeric = [col for col in numeric_cols if col in filtered_df.columns]
    
    avg_df = filtered_df.groupby('short_name')[available_numeric].mean().reset_index()

    metric_labels = {
        'duration': 'Average Duration (seconds)',
        'peak_rss': 'Average Peak RSS (MB)',
        'percent_cpu': 'Average CPU Percentage (%)',
        'realtime': 'Average Realtime (seconds)',
        'peak_vmem': 'Average Peak Virtual Memory (MB)',
        'storage_requested': 'Average Storage Requested (MB)',
        'time_requested': 'Average Time Requested (seconds)'
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

    st.subheader("Optimized Config Generator")
    st.write("Generate an automated configuration file based on average empirical metrics with a safety factor.")
    
    if st.button("Generate optimized.config"):
        config_lines = ["process {"]
        for _, row in avg_df.iterrows():
            proc_name = row['short_name']
            avg_duration = max(int(row.get('duration', 60)), 10)
            avg_rss = max(int(row.get('peak_rss', 512)), 256)
            
            config_lines.append(f"    withName: '{proc_name}' {{")
            config_lines.append(f"        cpus = 2")
            config_lines.append(f"        memory = '{int(avg_rss * 1.3)} MB'")
            config_lines.append(f"        time = '{int(avg_duration * 1.5)}s'")
            config_lines.append("    }")
        config_lines.append("}")
        
        config_content = "\n".join(config_lines)
        st.code(config_content, language="groovy")
        st.download_button(
            label="Download optimized.config File",
            data=config_content,
            file_name="optimized.config",
            mime="text/plain"
        )

    st.subheader("Detailed Process Data Table")
    st.dataframe(filtered_df, use_container_width=True)

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
    st.title("ML Model Training")
    st.write("Train machine learning models to predict resource requirements for Nextflow processes.")
    
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
        st.subheader("Training Status")
        if 'training_result' in st.session_state:
            result = st.session_state['training_result']
            
            if result.get('success'):
                st.metric("Training Samples", result.get('training_samples', 0))
                st.metric("Models Trained", result.get('message', '').split(' ')[1])
                
                st.subheader("Model Results")
                model_results = result.get('model_results', {})
                
                for model_type, metrics in model_results.items():
                    if metrics.get('success'):
                        with st.expander(f"{model_type.title()} Model - R²: {metrics.get('test_r2', 0):.3f}"):
                            st.write(f"**Training Samples:** {metrics.get('training_samples', 0)}")
                            st.write(f"**Test Samples:** {metrics.get('test_samples', 0)}")
                            st.write(f"**Test R²:** {metrics.get('test_r2', 0):.4f}")
                            st.write(f"**Test RMSE:** {metrics.get('test_rmse', 0):.4f}")
                            st.write(f"**Test MAE:** {metrics.get('test_mae', 0):.4f}")
                            st.write(f"**CV R² Mean:** {metrics.get('cv_r2_mean', 0):.4f}")
                            
                            if metrics.get('feature_importance'):
                                fi = metrics['feature_importance']
                                fi_sorted = dict(sorted(fi.items(), key=lambda x: x[1], reverse=True)[:10])
                                fi_df = pd.DataFrame({
                                    'Feature': list(fi_sorted.keys()),
                                    'Importance': list(fi_sorted.values())
                                })
                                fig = px.bar(fi_df, x='Importance', y='Feature', orientation='h',
                                           title=f"Top 10 Features - {model_type.title()}")
                                st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.error(f"{model_type.title()} Model: {metrics.get('error', 'Failed')}")
                
                st.subheader("Feature Statistics")
                stats = result.get('feature_statistics', {})
                for metric, values in stats.items():
                    if isinstance(values, dict) and 'mean' in values:
                        with st.expander(f"{metric.replace('_', ' ').title()}"):
                            st.write(f"Mean: {values.get('mean', 0):.2f}")
                            st.write(f"Std: {values.get('std', 0):.2f}")
                            st.write(f"Min: {values.get('min', 0):.2f}")
                            st.write(f"Max: {values.get('max', 0):.2f}")
                            st.write(f"Median: {values.get('median', 0):.2f}")
                            st.write(f"P95: {values.get('p95', 0):.2f}")
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


def render_ml_predictions():
    st.title("ML Resource Predictions")
    st.write("Get ML-based predictions for resource requirements of Nextflow processes.")
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return
    
    # Fetch available processes
    processes = fetch_processes(API_KEY)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Prediction Request")
        
        # Cache clear button
        if st.button("Refresh Module List", key="refresh_processes"):
            fetch_processes.clear()
            st.rerun()
        
        if processes:
            # Create a searchable selectbox
            process_name = st.selectbox(
                "Select Module",
                options=processes,
                placeholder="Choose a module...",
                help="Select from modules with historical execution data"
            )
        else:
            process_name = st.text_input("Process Name", placeholder="e.g., BCFTOOLS_SORT")
        
        if st.button("Get Prediction", type="primary", use_container_width=True):
            if not process_name:
                st.error("Please select or enter a process name")
            else:
                with st.spinner("Getting predictions..."):
                    headers = {
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json"
                    }
                    try:
                        response = requests.get(
                            f"{API_BASE_URL}/ml/predict?process_name={process_name}",
                            headers=headers
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            st.session_state['prediction_result'] = result
                            if result.get('success'):
                                st.success(f"Predictions for {result.get('module_name', 'module')}")
                            else:
                                st.error(result.get('message', 'Prediction failed'))
                        else:
                            st.error(f"Prediction failed: {response.text}")
                    except Exception as e:
                        st.error(f"Connection failed: {e}")
    
    with col2:
        st.subheader("Prediction Results")
        if 'prediction_result' in st.session_state:
            result = st.session_state['prediction_result']
            
            if result.get('success'):
                st.metric("Module", result.get('module_name', 'N/A'))
                
                predictions = result.get('predictions', {})
                
                col_mem, col_time, col_cpu = st.columns(3)
                
                with col_mem:
                    mem_pred = predictions.get('memory', {})
                    st.metric(
                        "Memory",
                        f"{mem_pred.get('value', 0):.1f} {mem_pred.get('unit', 'MB')}",
                        delta=f"P95 margin: {mem_pred.get('safety_margin', 1)}x"
                    )
                
                with col_time:
                    time_pred = predictions.get('time', {})
                    st.metric(
                        "Time",
                        f"{time_pred.get('value', 0):.1f} {time_pred.get('unit', 'seconds')}",
                        delta=f"P95 margin: {time_pred.get('safety_margin', 1)}x"
                    )
                
                with col_cpu:
                    cpu_pred = predictions.get('cpu', {})
                    st.metric(
                        "CPU",
                        f"{int(cpu_pred.get('value', 1))} {cpu_pred.get('unit', 'cores')}",
                        delta=f"P95 margin: {cpu_pred.get('safety_margin', 1)}x"
                    )
                
                st.subheader("Nextflow Config")
                nextflow_config = result.get('nextflow_config', {})
                module_name = result.get('module_name', 'module')
                config_text = f"""process {{
    withName: '{module_name}' {{
        cpus = {nextflow_config.get('cpus', 1)}
        memory = '{nextflow_config.get('memory', '100 MB')}'
        time = '{nextflow_config.get('time', '1h')}'
    }}
}}"""
                st.code(config_text, language="groovy")
                
                st.download_button(
                    label="Download Config Snippet",
                    data=config_text,
                    file_name=f"{module_name}.config",
                    mime="text/plain"
                )
                
                st.info(result.get('message', ''))
            else:
                st.error(f"Prediction failed: {result.get('message', 'Unknown error')}")
        else:
            st.info("No predictions yet. Enter a process name and click 'Get Prediction'.")

@st.cache_data
def fetch_all_optimizations(api_key_val, institute_id=None):
    """Fetch all optimization recommendations from the API."""
    headers = {
        "Authorization": f"Bearer {api_key_val}",
        "Content-Type": "application/json"
    }
    try:
        url = f"{API_BASE_URL}/ml/optimizations"
        if institute_id:
            url += f"?institute_id={institute_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None


def render_optimization():
    st.title("Process Optimization Recommendations")
    st.write("Get data-driven optimization recommendations for Nextflow processes based on historical execution data.")
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return
    
    # Fetch available processes
    processes = fetch_processes(API_KEY)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Optimization Request")
        
        # Cache clear button
        if st.button("Refresh Module List", key="refresh_opt_processes"):
            fetch_processes.clear()
            st.rerun()
        
        # Download all optimizations button
        if st.button("Download All Optimizations", use_container_width=True):
            with st.spinner("Fetching all optimizations..."):
                all_opts = fetch_all_optimizations(API_KEY)
                if all_opts and all_opts.get('success'):
                    # Generate config file content
                    config_lines = ["// Auto-generated Nextflow configuration", "// Generated by GW-Repo ML Optimization", "process {"]
                    for opt in all_opts.get('optimizations', []):
                        module = opt.get('module_name', 'unknown')
                        rec = opt.get('recommended_config', {})
                        config_lines.append(f"    withName: '{module}' {{")
                        config_lines.append(f"        memory = '{rec.get('memory', '1 GB')}'")
                        config_lines.append(f"        time = '{rec.get('time', '1h')}'")
                        config_lines.append(f"        cpus = {rec.get('cpus', 1)}")
                        config_lines.append("    }")
                    config_lines.append("}")
                    
                    config_content = "\n".join(config_lines)
                    st.download_button(
                        label="Download nextflow_optimized.config",
                        data=config_content,
                        file_name="nextflow_optimized.config",
                        mime="text/plain",
                        key="download_all_config"
                    )
                    
                    # Also show as JSON
                    json_content = json.dumps(all_opts.get('optimizations', []), indent=2)
                    st.download_button(
                        label="Download optimizations.json",
                        data=json_content,
                        file_name="optimizations.json",
                        mime="application/json",
                        key="download_all_json"
                    )
                    
                    st.success(f"Fetched optimizations for {all_opts.get('modules', 0)} modules")
                else:
                    st.error("Failed to fetch optimizations")
        
        st.divider()
        
        if processes:
            process_name = st.selectbox(
                "Select Module",
                options=processes,
                placeholder="Choose a module...",
                help="Select from modules with historical execution data"
            )
        else:
            process_name = st.text_input("Process Name", placeholder="e.g., BCFTOOLS_SORT")
        
        institute_id = st.text_input("Institute ID (optional)", value="DKFZ")
        
        if st.button("Get Recommendations", type="primary", use_container_width=True):
            if not process_name:
                st.error("Please select or enter a module name")
            else:
                with st.spinner("Analyzing historical data..."):
                    headers = {
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json"
                    }
                    try:
                        response = requests.get(
                            f"{API_BASE_URL}/ml/optimization/{process_name}?institute_id={institute_id if institute_id else ''}",
                            headers=headers
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            st.session_state['optimization_result'] = result
                            if result.get('success'):
                                st.success(f"Recommendations for {result.get('module_name', result.get('process_name', 'module'))}")
                            else:
                                st.error(result.get('message', 'Optimization failed'))
                        else:
                            st.error(f"Optimization failed: {response.text}")
                    except Exception as e:
                        st.error(f"Connection failed: {e}")
    
    with col2:
        st.subheader("Optimization Results")
        if 'optimization_result' in st.session_state:
            result = st.session_state['optimization_result']
            
            if result.get('success'):
                st.metric("Module", result.get('module_name', result.get('process_name', 'N/A')))
                st.metric("Historical Samples", result.get('historical_samples', 0))
                
                st.subheader("Resource Statistics")
                
                col1_stats, col2_stats = st.columns(2)
                
                with col1_stats:
                    if result.get('memory'):
                        mem = result['memory']
                        st.metric("Memory (mean)", f"{mem.get('mean', 0):.1f} MB")
                        st.metric("Memory (P95)", f"{mem.get('p95', 0):.1f} MB")
                        st.metric("Memory (max)", f"{mem.get('max', 0):.1f} MB")
                    
                    if result.get('duration'):
                        dur = result['duration']
                        st.metric("Duration (mean)", f"{dur.get('mean', 0):.2f} s")
                        st.metric("Duration (P95)", f"{dur.get('p95', 0):.2f} s")
                        st.metric("Duration (max)", f"{dur.get('max', 0):.2f} s")
                
                with col2_stats:
                    if result.get('cpu_utilization'):
                        cpu = result['cpu_utilization']
                        st.metric("CPU Util (mean)", f"{cpu.get('mean', 0):.1f}%")
                        st.metric("CPU Util (max)", f"{cpu.get('max', 0):.1f}%")
                    
                    if result.get('energy'):
                        energy = result['energy']
                        st.metric("Energy (mean)", f"{energy.get('mean', 0):.2f} mWh")
                        st.metric("Energy (max)", f"{energy.get('max', 0):.2f} mWh")
                    
                    if result.get('co2'):
                        co2 = result['co2']
                        st.metric("CO2 (mean)", f"{co2.get('mean', 0):.2f} mg")
                        st.metric("CO2 (max)", f"{co2.get('max', 0):.2f} mg")
                
                st.subheader("Recommended Configuration")
                rec_config = result.get('recommended_config', {})
                module_name = result.get('module_name', result.get('process_name', ''))
                st.code(f"""process {{
    withName: '{module_name}' {{
        memory = '{rec_config.get('memory', '1 GB')}'
        time = '{rec_config.get('time', '1h')}'
        cpus = {rec_config.get('cpus', 1)}
    }}
}}""", language="groovy")
                
                # Download single module config
                single_config = f"""process {{
    withName: '{module_name}' {{
        memory = '{rec_config.get('memory', '1 GB')}'
        time = '{rec_config.get('time', '1h')}'
        cpus = {rec_config.get('cpus', 1)}
    }}
}}"""
                st.download_button(
                    label=f"Download {module_name}.config",
                    data=single_config,
                    file_name=f"{module_name}.config",
                    mime="text/plain",
                    key=f"download_{module_name}"
                )
                
                if result.get('insights'):
                    st.subheader("Insights")
                    for insight in result['insights']:
                        st.info(insight)
            else:
                st.error(f"Optimization failed: {result.get('message', 'Unknown error')}")
        else:
            st.info("No recommendations yet. Enter a process name and click 'Get Recommendations'.")

def render_model_performance():
    st.title("Model Performance Dashboard")
    st.write("Monitor the performance and accuracy of trained ML models.")
    
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
                model_type = model.get('model_type', 'unknown')
                model_name = model.get('model_name', 'unknown')
                accuracy = json.loads(model.get('accuracy_metrics', '{}'))
                
                with st.expander(f"{model_type.title()} Model ({model_name}) - Trained: {model.get('trained_at', 'N/A')}"):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Test R²", f"{accuracy.get('test_r2', 0):.4f}")
                        st.metric("Test RMSE", f"{accuracy.get('test_rmse', 0):.4f}")
                    
                    with col2:
                        st.metric("Test MAE", f"{accuracy.get('test_mae', 0):.4f}")
                        st.metric("CV R² Mean", f"{accuracy.get('cv_r2_mean', 0):.4f}")
                    
                    with col3:
                        st.metric("Training Samples", model.get('training_samples', 0))
                        st.metric("Model Path", model.get('model_artifact_path', 'N/A'))
                    
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
    elif page == "ML Predictions":
        render_ml_predictions()
    elif page == "Optimization":
        render_optimization()
    elif page == "Model Performance":
        render_model_performance()

if __name__ == "__main__":
    main()
