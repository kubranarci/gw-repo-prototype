import streamlit as st
import plotly.express as px
import pandas as pd
import requests
import os
import re

st.set_page_config(page_title="Nextflow Resource Monitoring", layout="wide")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost")
env_api_key = os.getenv("API_KEY", "")

with st.sidebar:
    st.subheader("Authentication")
    API_KEY = st.text_input("API Key", value=env_api_key, type="password")

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

def main():
    st.title("Nextflow Process Resource Monitoring")
    
    if not API_KEY:
        st.warning("Please enter your API key in the sidebar to authenticate.")
        return

    df = fetch_process_data(API_KEY)
    render_resource_charts(df)

if __name__ == "__main__":
    main()