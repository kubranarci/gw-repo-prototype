import typer
import requests
import json
import re
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:80")
INSTITUTE_ID = os.getenv("INSTITUTE_ID", "DKFZ")

def duration_to_seconds(duration: str) -> float:
    if duration == "-" or not duration:
        return 0.0  
    
    pattern = re.compile(r'(?:(\d+\.?\d*)d)?\s*(?:(\d+\.?\d*)h)?\s*(?:(\d+\.?\d*)m)?\s*(?:(\d+\.?\d*)s)?\s*(?:(\d+\.?\d*)ms)?')
    match = pattern.fullmatch(duration.strip())

    if not match:
        raise ValueError(f"Error in converting duration: {duration}")

    days = float(match.group(1)) if match.group(1) else 0
    hours = float(match.group(2)) if match.group(2) else 0
    minutes = float(match.group(3)) if match.group(3) else 0
    seconds = float(match.group(4)) if match.group(4) else 0
    milliseconds = float(match.group(5)) if match.group(5) else 0

    return days * 86400 + hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

def parse_memory_value(value):
    if not value or value == "-":
        return None
    match = re.match(r'^([\d.]+)\s*([KMGT]B?)?', value.strip(), re.IGNORECASE)
    if not match:
        try:
            return float(value)
        except ValueError:
            return None
    num = float(match.group(1))
    unit = (match.group(2) or "MB").upper()
    if unit in ("K", "KB"):
        return num / 1024
    elif unit in ("M", "MB"):
        return num
    elif unit in ("G", "GB"):
        return num * 1024
    elif unit in ("T", "TB"):
        return num * (1024 ** 2)
    return num

def parse_trace_time(time_str):
    if not time_str or time_str == "-":
        return 0.0
    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f").timestamp()
    except ValueError:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return 0.0

def get_nextflow_version(bco_data: dict):
    exec_domain = bco_data.get('execution_domain', {})
    prerequisites = exec_domain.get('software_prerequisites', [])
    nextflow_info = next((item for item in prerequisites if item.get('name') == 'Nextflow'), None)
    return nextflow_info['version'] if nextflow_info else "unknown"

def get_workflow_metadata_from_bco(bco_data: dict):
    session_id = bco_data.get("object_id", "").replace("urn:uuid:", "")
    prov_domain = bco_data.get("provenance_domain", {})
    start_time_str = prov_domain.get("created", "")
    
    try:
        start_time = datetime.fromisoformat(start_time_str).timestamp()
    except ValueError:
        start_time = 0.0

    return {
        "id": session_id,
        "start_time": start_time,
        "duration": 0.0,
        "run_name": prov_domain.get("name", "unknown_pipeline"),
        "nextflow_version": get_nextflow_version(bco_data),
        "revision_id": prov_domain.get("version", ""),
        "final_state": "COMPLETED"
    }

def get_process_execution_data(trace_file: Path, workflow_id: str): 
    with open(trace_file, "r") as f:
        lines = f.readlines()

    if not lines or len(lines) < 2:
        return []

    # Başlıkları temizle (Büyük/küçük harf duyarsız hale getiriyoruz)
    headers = [h.strip().lstrip('#').lower() for h in lines[0].strip().split("\t")]
    
    data = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = [v.strip() for v in line.split("\t")]
        # Değerler başlıklardan azsa eksikleri tamamla
        if len(values) < len(headers):
            values.extend([''] * (len(headers) - len(values)))
        
        row_dict = dict(zip(headers, values))
        data.append(row_dict)

    process_execution_data = []
    for item in data:
        process_name = item.get("process") or item.get("name", "unknown")
        original_hash = item.get('hash')
        
        unique_process_id = f"{workflow_id}_{original_hash}"
        
        def get_val(*keys):
            for k in keys:
                val = item.get(k)
                if val and val != "-" and val != "":
                    return val
            return None

        # Gerçek kullanım değerlerini çekme
        pct_cpu_raw = get_val("%cpu", "pct_cpu")
        pct_cpu = float(pct_cpu_raw.replace("%", "")) if pct_cpu_raw else 0.0

        pct_mem_raw = get_val("%mem", "pct_mem")
        pct_mem = float(pct_mem_raw.replace("%", "")) if pct_mem_raw else 0.0

        exit_raw = get_val("exit")
        exit_code = int(float(exit_raw)) if exit_raw else None

        process_execution_data.append({
            "id": unique_process_id,  
            "workflow_execution_id": workflow_id,  
            "process_name": process_name,
            "module_name": get_val("module") or "",
            "container_name": get_val("container") or "",  # Dosyada yoksa boş kalır
            "final_status": get_val("status"),
            "exit_code": exit_code,
            "start_time": parse_trace_time(get_val("submit", "start")),  
            "duration": duration_to_seconds(get_val("duration") or "0s"),
            "cpus_requested": None, # Dosyada yok
            "time_requested": duration_to_seconds(get_val("time") or "0s"),  
            "storage_requested": parse_memory_value(get_val("disk")),  
            "memory_requested": None, # Dosyada yok
            "realtime": duration_to_seconds(get_val("realtime") or "0s"),
            "queue_name": get_val("queue") or "",
            "percent_cpu": pct_cpu,
            "percent_memory": pct_mem,
            "peak_rss": parse_memory_value(get_val("peak_rss")),
            "peak_vmem": parse_memory_value(get_val("peak_vmem")),
            "read_char": parse_memory_value(get_val("rchar")),
            "write_char": parse_memory_value(get_val("wchar")),
        })    
    return process_execution_data

def extract_process_id(name: str) -> str:
    return f"{name[:2]}/{name[2:8]}"

def get_provenance_data(bco_data, workflow_id: str):
    process_executions_inputs = []
    process_executions_outputs = []

    for step in bco_data.get("description_domain", {}).get("pipeline_steps", []):
        original_hash = extract_process_id(step["name"])
        unique_process_id = f"{workflow_id}_{original_hash}"
    
        input_files = list(set([file["uri"] for file in step.get("input_list", [])]))
        output_files = list(set([file["uri"] for file in step.get("output_list", [])]))
    
        for input_file in input_files:
            process_executions_inputs.append({
                "process_execution_id": unique_process_id,
                "filename": input_file,
                "xxhash128": "NOT_AVAILABLE",
            })
            
        for output_file in output_files:
            process_executions_outputs.append({
                "process_execution_id": unique_process_id,
                "filename": output_file,
                "xxhash128": "NOT_AVAILABLE",
            })

    return (process_executions_inputs, process_executions_outputs)

def find_and_group_runs(pipeline_info_dir: Path):
    runs = {}
    
    for trace_file in pipeline_info_dir.glob("execution_trace_*.txt"):
        match = re.search(r"execution_trace_(.+)\.txt", trace_file.name)
        if match:
            runs[match.group(1)] = {"trace": trace_file}
            
    for bco_file in pipeline_info_dir.glob("manifest_*.bco.json"):
        match = re.search(r"manifest_(.+)\.bco\.json", bco_file.name)
        if match:
            ts = match.group(1)
            if ts in runs:
                runs[ts]["bco"] = bco_file
                
    return {ts: files for ts, files in runs.items() if "bco" in files and "trace" in files}

@app.command()
def submit_directory(
    pipeline_info_dir: Path = typer.Argument(..., help="Path to the pipeline_info directory containing trace and bco files"),
    api_key: str = typer.Option(None, help="API key for authentication")
):
    
    if api_key is None:
        api_key = os.getenv("API_KEY")
        if not api_key:
            typer.echo("API key must be provided either as argument or API_KEY environment variable", err=True)
            return
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    grouped_runs = find_and_group_runs(pipeline_info_dir)
    
    if not grouped_runs:
        typer.echo("No valid execution pairs (trace + bco) found in the specified directory.", err=True)
        return

    typer.echo(f"Found {len(grouped_runs)} workflow runs to process. Institute target: {INSTITUTE_ID}")

    for timestamp, files in grouped_runs.items():
        trace_file = files["trace"]
        bco_file = files["bco"]
        
        typer.echo(f"\n--- Processing Run: {timestamp} ---")
        
        with open(bco_file, "r") as f:
            bco_data = json.load(f)

        workflow_execution_data = get_workflow_metadata_from_bco(bco_data)
        
        response = requests.post(f"{API_BASE_URL}/workflows/", json=workflow_execution_data, headers=headers)
        
        if response.status_code != 200:
            typer.echo(f"Failed to submit workflow execution: {response.text}", err=True)
            continue
            
        typer.echo("Workflow execution submitted successfully")

        workflow_id = workflow_execution_data["id"]
        process_execution_data = get_process_execution_data(trace_file, workflow_id)
        
        for entry in process_execution_data:
            response = requests.post(f"{API_BASE_URL}/processes/", json=entry, headers=headers)
            if response.status_code != 200:
                typer.echo(f"Failed to submit process execution: {entry['process_name']} - {response.text}", err=True)
                break
        else:
            typer.echo("All process executions submitted successfully")

        (file_inputs, file_outputs) = get_provenance_data(bco_data, workflow_id)
        
        for entry in file_inputs:
            response = requests.post(f"{API_BASE_URL}/input_files/", json=entry, headers=headers)
            if response.status_code != 200:
                typer.echo(f"Failed to submit input file: {entry['filename']} - API Response: {response.text}", err=True)
                break
                
        for entry in file_outputs:
            response = requests.post(f"{API_BASE_URL}/output_files/", json=entry, headers=headers)
            if response.status_code != 200:
                typer.echo(f"Failed to submit output file: {entry['filename']} - API Response: {response.text}", err=True)
                break
        else:
            typer.echo("All input and output files submitted successfully")

if __name__ == "__main__":
    app()