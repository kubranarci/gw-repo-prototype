import typer
import requests
import json
import re
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Optional, Dict, List, Tuple

load_dotenv()

app = typer.Typer()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:80")
INSTITUTE_ID = os.getenv("INSTITUTE_ID", "DKFZ")


# ==================== Utility Functions ====================

def parse_energy_value(value: str) -> float:
    """
    Parse energy values like '35.26 mWh', '75.75 uWh', '0 Wh' to mWh.
    Handles: Wh, mWh, uWh (micro), kWh
    """
    if not value or value == "-":
        return 0.0
    
    value = value.strip()
    
    # Match number and unit
    match = re.match(r'^([\d.]+)\s*([kmu]?Wh)?', value, re.IGNORECASE)
    if not match:
        return 0.0
    
    num = float(match.group(1))
    unit = (match.group(2) or "Wh").lower()
    
    # Convert to mWh
    if unit == "kwh":
        return num * 1000.0
    elif unit == "mwh":
        return num
    elif unit == "uwh":
        return num / 1000.0
    else:  # Wh
        return num * 1000.0


def parse_co2_value(value: str) -> float:
    """
    Parse CO2 values like '16.92 mg', '36.36 ug', '0 g' to mg.
    Handles: g, mg, ug
    """
    if not value or value == "-":
        return 0.0
    
    value = value.strip()
    
    # Match number and unit
    match = re.match(r'^([\d.]+)\s*([mgu]?g)?', value, re.IGNORECASE)
    if not match:
        return 0.0
    
    num = float(match.group(1))
    unit = (match.group(2) or "g").lower()
    
    # Convert to mg
    if unit == "g":
        return num * 1000.0
    elif unit == "mg":
        return num
    elif unit == "ug":
        return num / 1000.0
    else:
        return num


def parse_time_to_seconds(time_str: str) -> float:
    """Parse time strings like '14s 985ms', '48s 129ms', '0ms' to seconds."""
    if not time_str or time_str == "-":
        return 0.0
    
    total_seconds = 0.0
    
    # Match days, hours, minutes, seconds, milliseconds
    patterns = [
        (r'(\d+(?:\.\d+)?)\s*d', 86400),
        (r'(\d+(?:\.\d+)?)\s*h', 3600),
        (r'(\d+(?:\.\d+)?)\s*m(?!s)', 60),  # m but not ms
        (r'(\d+(?:\.\d+)?)\s*s(?!\w)', 1),  # s but not followed by word chars
        (r'(\d+(?:\.\d+)?)\s*ms', 0.001),
    ]
    
    for pattern, multiplier in patterns:
        match = re.search(pattern, time_str)
        if match:
            total_seconds += float(match.group(1)) * multiplier
    
    return total_seconds

def duration_to_seconds(duration: str) -> float:
    """Original duration parser - kept for backward compatibility."""
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


# ==================== CO2 Footprint Parsing ====================

def parse_co2footprint_trace(trace_file: Path) -> List[Dict]:
    """
    Parse co2footprint_trace_*.txt files.
    Returns list of dicts with CO2 data per process.
    """
    if not trace_file.exists():
        return []
    
    with open(trace_file, "r") as f:
        lines = f.readlines()
    
    if not lines or len(lines) < 2:
        return []
    
    # Parse headers
    headers = [h.strip().lower() for h in lines[0].strip().split("\t")]
    
    data = []
    for line in lines[1:]:
        if not line.strip():
            continue
        
        values = [v.strip() for v in line.split("\t")]
        if len(values) < len(headers):
            values.extend([''] * (len(headers) - len(values)))
        
        row_dict = dict(zip(headers, values))
        data.append(row_dict)
    
    co2_data_list = []
    for item in data:
        task_name = item.get("name", "")
        
        # Extract process hash from name (last part before parentheses)
        # e.g., "NFCORE_VARIANTBENCHMARKING:VARIANTBENCHMARKING:PREPARE_VCFS_TRUTH:BCFTOOLS_REHEADER_TRUTH (HG002)"
        # We'll match by process name pattern
        process_name_clean = re.sub(r'\s*\(.*\)', '', task_name).split(':')[-1] if ':' in task_name else task_name
        
        co2_data_list.append({
            "process_name": process_name_clean,
            "task_name": task_name,
            "energy_consumption_mwh": parse_energy_value(item.get("energy_consumption", "0")),
            "co2e_mg": parse_co2_value(item.get("co2e", "0")),
            "co2e_market_mg": parse_co2_value(item.get("co2e_market", "0")) if item.get("co2e_market") and item.get("co2e_market") != "-" else None,
            "carbon_intensity_gco2e_kwh": float(item.get("carbon_intensity", "0").split()[0]) if item.get("carbon_intensity") else 0.0,
            "powerdraw_cpu_w": float(item.get("powerdraw_cpu", "0").split()[0]) if item.get("powerdraw_cpu") else 0.0,
            "cpu_model": item.get("cpu_model", ""),
            "raw_energy_processor_mwh": parse_energy_value(item.get("raw_energy_processor", "0")),
            "raw_energy_memory_mwh": parse_energy_value(item.get("raw_energy_memory", "0")),
            "percent_cpu": float(item.get("%cpu", "0").replace("%", "")) if item.get("%cpu") else 0.0,
            "realtime_sec": parse_time_to_seconds(item.get("realtime", "0")),
        })
    
    return co2_data_list


def parse_co2footprint_summary(summary_file: Path) -> Optional[Dict]:
    """
    Parse co2footprint_summary_*.txt files.
    Returns dict with workflow-level CO2 summary.
    """
    if not summary_file.exists():
        return None
    
    with open(summary_file, "r") as f:
        content = f.read()
    
    # Extract values using regex
    patterns = {
        "total_co2e_mg": r'CO₂e emissions:\s*([\d.]+)\s*(mg|g|ug)',
        "total_energy_mwh": r'Energy consumption:\s*([\d.]+)\s*(mWh|Wh|uWh|kWh)',
        "car_km_equivalent": r'([\d.]+[Ee]?[-+]?\d*)\s*km travelled by car',
        "tree_sequestration_time": r'(\d+)min\s*(\d+)s',
    }
    
    result = {}
    
    # Parse CO2e emissions
    co2_match = re.search(patterns["total_co2e_mg"], content)
    if co2_match:
        value = float(co2_match.group(1))
        unit = co2_match.group(2)
        if unit == "g":
            value *= 1000
        elif unit == "ug":
            value /= 1000
        result["total_co2e_mg"] = value
    
    # Parse energy consumption
    energy_match = re.search(patterns["total_energy_mwh"], content)
    if energy_match:
        value = float(energy_match.group(1))
        unit = energy_match.group(2)
        if unit == "Wh":
            value *= 1000
        elif unit == "uWh":
            value /= 1000
        elif unit == "kWh":
            value *= 1000000
        result["total_energy_mwh"] = value
    
    # Parse car km equivalent
    car_match = re.search(patterns["car_km_equivalent"], content)
    if car_match:
        try:
            result["car_km_equivalent"] = float(car_match.group(1))
        except ValueError:
            result["car_km_equivalent"] = 0.0
    
    # Parse tree sequestration time (convert to seconds)
    tree_match = re.search(patterns["tree_sequestration_time"], content)
    if tree_match:
        minutes = int(tree_match.group(1))
        seconds = int(tree_match.group(2))
        result["tree_sequestration_time_sec"] = minutes * 60 + seconds
    
    # Set defaults for missing values
    result.setdefault("total_co2e_mg", 0.0)
    result.setdefault("total_energy_mwh", 0.0)
    result.setdefault("car_km_equivalent", 0.0)
    result.setdefault("tree_sequestration_time_sec", 0)
    
    return result if result else None

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

        # Parse cpus_requested (handle both formats: "2" or "2.0")
        cpus_raw = get_val("cpus")
        cpus_requested = float(cpus_raw) if cpus_raw else None

        # Parse memory_requested (new format has "memory" field)
        memory_raw = get_val("memory")
        memory_requested = parse_memory_value(memory_raw) if memory_raw else None

        process_execution_data.append({
            "id": unique_process_id,  
            "workflow_execution_id": workflow_id,  
            "process_name": process_name,
            "module_name": get_val("module") or "",
            "container_name": get_val("container") or "",
            "final_status": get_val("status"),
            "exit_code": exit_code,
            "start_time": parse_trace_time(get_val("submit", "start")),  
            "duration": duration_to_seconds(get_val("duration") or "0s"),
            "cpus_requested": cpus_requested,
            "time_requested": duration_to_seconds(get_val("time") or "0s"),  
            "storage_requested": parse_memory_value(get_val("disk")),  
            "memory_requested": memory_requested,
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

def extract_timestamp_from_filename(filename: str) -> Optional[str]:
    """
    Extract timestamp from various filename patterns.
    Handles:
      - execution_trace_2026-08-19_09-48-39.txt → 2026-08-19_09-48-39
      - co2footprint_trace_2026-08-19_10-02-54.txt → 2026-08-19_10-02-54
      - co2footprint_trace_20260819-35325328.txt → 20260819-35325328
      - manifest_2026-08-19_09-48-39.bco.json → 2026-08-19_09-48-39
    """
    # Pattern 1: YYYY-MM-DD_HH-MM-SS
    match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    
    # Pattern 2: YYYYMMDD-NNNNNNNN (date + nanoseconds)
    match = re.search(r'(\d{8}-\d+)', filename)
    if match:
        return match.group(1)
    
    return None


def timestamp_to_datetime(ts: str) -> Optional[datetime]:
    """
    Convert timestamp string to datetime for comparison.
    """
    # Try YYYY-MM-DD_HH-MM-SS format
    try:
        return datetime.strptime(ts, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        pass
    
    # Try YYYYMMDD-NNNNNNNN format (date + nanoseconds)
    try:
        match = re.match(r'(\d{4})(\d{2})(\d{2})-(\d+)', ts)
        if match:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            # Extract time from nanoseconds if possible (rough approximation)
            nanos = int(match.group(4))
            # Assume nanoseconds represent time of day (very rough)
            # This is a heuristic - actual matching should use date primarily
            return datetime(year, month, day)
    except ValueError:
        pass
    
    return None


def timestamps_match(ts1: str, ts2: str, tolerance_minutes: int = 5) -> bool:
    """
    Check if two timestamps match within a tolerance.
    Returns True if:
      - Exact string match, OR
      - Datetime match within tolerance
    """
    # Exact match
    if ts1 == ts2:
        return True
    
    # Try datetime comparison
    dt1 = timestamp_to_datetime(ts1)
    dt2 = timestamp_to_datetime(ts2)
    
    if dt1 and dt2:
        diff = abs((dt1 - dt2).total_seconds())
        
        # If both have time components, use strict tolerance (5 min)
        # If one is date-only, use 24 hour tolerance
        has_time1 = '_' in ts1 or '-' in ts1[8:10] if len(ts1) > 8 else False
        has_time2 = '_' in ts2 or '-' in ts2[8:10] if len(ts2) > 8 else False
        
        if has_time1 and has_time2:
            return diff <= (tolerance_minutes * 60)
        else:
            # Date-only match: allow 24 hours
            return diff <= (24 * 60 * 60)
    
    return False


def find_and_group_runs(pipeline_info_dir: Path) -> Dict[str, Dict]:
    """
    Groups files by execution run using flexible timestamp matching.
    Handles patterns like:
      - execution_trace_2026-08-19_09-48-39.txt
      - co2footprint_trace_20260819-35325328.txt
      - manifest_2026-08-19_09-48-39.bco.json
    
    Returns dict mapping run_id to file paths:
    {
        "2026-08-19_09-48-39": {
            "trace": Path(...),
            "bco": Path(...),  # optional
            "co2_trace": Path(...),  # optional
            "co2_summary": Path(...)  # optional
        }
    }
    """
    runs = {}
    
    # Collect all execution trace files
    for trace_file in pipeline_info_dir.glob("execution_trace_*.txt"):
        ts = extract_timestamp_from_filename(trace_file.name)
        if ts:
            runs[ts] = {"trace": trace_file, "timestamp": ts}
    
    # Match BCO files
    for bco_file in pipeline_info_dir.glob("manifest_*.bco.json"):
        ts = extract_timestamp_from_filename(bco_file.name)
        if ts:
            # Try exact match first
            if ts in runs:
                runs[ts]["bco"] = bco_file
            else:
                # Try fuzzy match
                for run_ts in runs:
                    if timestamps_match(run_ts, ts):
                        runs[run_ts]["bco"] = bco_file
                        break
    
    # Match CO2 trace files
    for co2_trace in pipeline_info_dir.glob("co2footprint_trace_*.txt"):
        ts = extract_timestamp_from_filename(co2_trace.name)
        if ts:
            # Try exact match first
            if ts in runs:
                runs[ts]["co2_trace"] = co2_trace
            else:
                # Try fuzzy match
                for run_ts in runs:
                    if timestamps_match(run_ts, ts):
                        runs[run_ts]["co2_trace"] = co2_trace
                        break
    
    # Match CO2 summary files
    for co2_summary in pipeline_info_dir.glob("co2footprint_summary_*.txt"):
        ts = extract_timestamp_from_filename(co2_summary.name)
        if ts:
            # Try exact match first
            if ts in runs:
                runs[ts]["co2_summary"] = co2_summary
            else:
                # Try fuzzy match
                for run_ts in runs:
                    if timestamps_match(run_ts, ts):
                        runs[run_ts]["co2_summary"] = co2_summary
                        break
    
    # Filter to only include runs with at least a trace file
    return {ts: files for ts, files in runs.items() if "trace" in files}

@app.command()
def submit_directory(
    pipeline_info_dir: Path = typer.Argument(..., help="Path to the pipeline_info directory containing trace and bco files"),
    work_dir: Optional[Path] = typer.Option(None, help="Path to the work directory for disk usage scanning"),
    api_key: str = typer.Option(None, help="API key for authentication"),
    retrain: bool = typer.Option(False, "--retrain", help="Trigger manual model retraining after submission")
):
    """
    Submit pipeline execution data to the API.
    
    Required files:
      - execution_trace_*.txt (always required)
    
    Optional files (processed if present):
      - manifest_*.bco.json (provenance data)
      - co2footprint_trace_*.txt (CO2 per-process data)
      - co2footprint_summary_*.txt (CO2 workflow summary)
    """
    
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
        typer.echo("No execution trace files found in the specified directory.", err=True)
        return

    typer.echo(f"Found {len(grouped_runs)} workflow runs to process. Institute: {INSTITUTE_ID}")

    for timestamp, files in grouped_runs.items():
        trace_file = files["trace"]
        bco_file = files.get("bco")
        co2_trace = files.get("co2_trace")
        co2_summary = files.get("co2_summary")
        
        typer.echo(f"\n--- Processing Run: {timestamp} ---")
        
        # Get workflow metadata from BCO if available, otherwise create minimal metadata
        if bco_file:
            typer.echo(f"  Found BCO file: {bco_file.name}")
            with open(bco_file, "r") as f:
                bco_data = json.load(f)
            workflow_execution_data = get_workflow_metadata_from_bco(bco_data)
        else:
            typer.echo("  No BCO file found - using minimal metadata")
            workflow_execution_data = {
                "id": f"workflow_{timestamp.replace('-', '').replace('_', '').replace(':', '')}",
                "start_time": datetime.now(timezone.utc).timestamp(),
                "duration": 0.0,
                "run_name": f"pipeline_{timestamp}",
                "nextflow_version": "unknown",
                "revision_id": "",
                "final_state": "COMPLETED",
                "institute_id": INSTITUTE_ID,
            }
        
        # Always include institute_id
        workflow_execution_data["institute_id"] = INSTITUTE_ID
        
        # Submit workflow
        response = requests.post(f"{API_BASE_URL}/workflows/", json=workflow_execution_data, headers=headers)
        
        if response.status_code != 200:
            typer.echo(f"  ✗ Failed to submit workflow: {response.text}", err=True)
            continue
            
        typer.echo("  ✓ Workflow submitted")

        workflow_id = workflow_execution_data["id"]
        
        # Submit process execution data
        process_execution_data = get_process_execution_data(trace_file, workflow_id)
        
        # Add institute_id to each process
        for entry in process_execution_data:
            entry["institute_id"] = INSTITUTE_ID
        
        # Scan work directory if provided (privacy-safe: only sizes, no filenames)
        work_metrics = {}
        if work_dir:
            from work_scanner import scan_work_directory
            # Extract task hashes from process execution data
            task_hashes = []
            for entry in process_execution_data:
                # Extract hash from ID: format is "{workflow_id}_{hash}" where hash contains "/"
                # Hash format is "XX/XXXXXX" so we look for the last underscore before the slash
                entry_id = entry["id"]
                # Find position of "/" and work backwards to find the underscore before it
                slash_pos = entry_id.find("/")
                if slash_pos > 0:
                    # Find the underscore right before the directory prefix (XX/)
                    underscore_pos = entry_id.rfind("_", 0, slash_pos - 1)
                    if underscore_pos > 0:
                        task_hash = entry_id[underscore_pos + 1:]
                        task_hashes.append(task_hash)
            
            if task_hashes:
                typer.echo(f"  Scanning work directory for {len(task_hashes)} tasks...")
                work_metrics = scan_work_directory(str(work_dir), task_hashes)
                typer.echo(f"  ✓ Scanned {len(work_metrics)} tasks")
        
        for entry in process_execution_data:
            # Extract hash to get work metrics (same logic as above)
            entry_id = entry["id"]
            slash_pos = entry_id.find("/")
            task_hash = None
            if slash_pos > 0:
                underscore_pos = entry_id.rfind("_", 0, slash_pos - 1)
                if underscore_pos > 0:
                    task_hash = entry_id[underscore_pos + 1:]
            
            # Add work directory metrics if available (privacy-safe: only numbers)
            if task_hash and task_hash in work_metrics:
                metrics = work_metrics[task_hash]
                entry["disk_usage_mb"] = metrics.get("disk_usage_mb")
                entry["read_bytes"] = metrics.get("read_bytes")
                entry["write_bytes"] = metrics.get("write_bytes")
                entry["peak_vmem_mb"] = metrics.get("peak_vmem_mb")
                entry["peak_rss_mb"] = metrics.get("peak_rss_mb")
            
            response = requests.post(f"{API_BASE_URL}/processes/", json=entry, headers=headers)
            if response.status_code != 200:
                typer.echo(f"  ✗ Failed to submit process {entry['process_name']}: {response.text}", err=True)
                break
        else:
            if work_metrics:
                typer.echo(f"  ✓ Submitted {len(process_execution_data)} processes with disk metrics")
            else:
                typer.echo(f"  ✓ Submitted {len(process_execution_data)} processes")
        
        # Submit BCO provenance data if available
        if bco_file:
            (file_inputs, file_outputs) = get_provenance_data(bco_data, workflow_id)
            
            for entry in file_inputs:
                response = requests.post(f"{API_BASE_URL}/input_files/", json=entry, headers=headers)
                if response.status_code != 200:
                    typer.echo(f"  ⚠ Failed to submit input file: {response.text}", err=True)
                    break
                    
            for entry in file_outputs:
                response = requests.post(f"{API_BASE_URL}/output_files/", json=entry, headers=headers)
                if response.status_code != 200:
                    typer.echo(f"  ⚠ Failed to submit output file: {response.text}", err=True)
                    break
            else:
                typer.echo(f"  ✓ Submitted {len(file_inputs)} inputs, {len(file_outputs)} outputs")
        
        # Submit CO2 trace data if available
        if co2_trace:
            typer.echo(f"  Found CO2 trace: {co2_trace.name}")
            co2_process_data = parse_co2footprint_trace(co2_trace)
            
            # Match CO2 data to processes by name
            co2_submitted = 0
            matched_co2 = set()
            
            for process_entry in process_execution_data:
                process_name = process_entry["process_name"]
                process_name_short = re.sub(r'\s*\(.*\)', '', process_name).split(':')[-1] if ':' in process_name else process_name
                
                # Find matching CO2 data
                for idx, co2_entry in enumerate(co2_process_data):
                    if idx in matched_co2:
                        continue
                    
                    co2_task_name = co2_entry["task_name"]
                    co2_process_name = co2_entry["process_name"]
                    
                    # Multiple matching strategies
                    match_found = False
                    
                    # Strategy 1: Exact short name match
                    if process_name_short.upper() == co2_process_name.upper():
                        match_found = True
                    
                    # Strategy 2: Process name contained in CO2 task name
                    if not match_found and process_name.upper() in co2_task_name.upper():
                        match_found = True
                    
                    # Strategy 3: Key words match (ignore sample names in parentheses)
                    if not match_found:
                        # Extract base process name without sample
                        process_base = re.sub(r'\s*\([^)]*\)', '', process_name).strip()
                        co2_base = re.sub(r'\s*\([^)]*\)', '', co2_task_name).strip()
                        
                        # Compare last 2-3 components of the colon-separated name
                        process_parts = process_base.split(':')[-2:] if ':' in process_base else [process_base]
                        co2_parts = co2_base.split(':')[-2:] if ':' in co2_base else [co2_base]
                        
                        if all(p.upper() == c.upper() for p, c in zip(process_parts, co2_parts)):
                            match_found = True
                    
                    if match_found:
                        co2_payload = {
                            "process_execution_id": process_entry["id"],
                            "energy_consumption_mwh": co2_entry["energy_consumption_mwh"],
                            "co2e_mg": co2_entry["co2e_mg"],
                            "co2e_market_mg": co2_entry["co2e_market_mg"],
                            "carbon_intensity_gco2e_kwh": co2_entry["carbon_intensity_gco2e_kwh"],
                            "powerdraw_cpu_w": co2_entry["powerdraw_cpu_w"],
                            "cpu_model": co2_entry["cpu_model"],
                            "raw_energy_processor_mwh": co2_entry["raw_energy_processor_mwh"],
                            "raw_energy_memory_mwh": co2_entry["raw_energy_memory_mwh"],
                        }
                        
                        response = requests.post(
                            f"{API_BASE_URL}/processes/co2",
                            json=co2_payload,
                            headers=headers
                        )
                        
                        if response.status_code == 200:
                            co2_submitted += 1
                            matched_co2.add(idx)
                        else:
                            typer.echo(f"    ⚠ CO2 submit failed for {process_name}: {response.status_code}", err=True)
                        break
            
            typer.echo(f"  ✓ Submitted CO2 data for {co2_submitted}/{len(co2_process_data)} processes")
        
        # Submit CO2 summary if available
        if co2_summary:
            typer.echo(f"  Found CO2 summary: {co2_summary.name}")
            co2_summary_data = parse_co2footprint_summary(co2_summary)
            
            if co2_summary_data:
                response = requests.post(
                    f"{API_BASE_URL}/workflows/{workflow_id}/co2/",
                    json=co2_summary_data,
                    headers=headers
                )
                
                if response.status_code == 200:
                    typer.echo(f"  ✓ Workflow CO2 summary: {co2_summary_data['total_co2e_mg']:.2f} mg CO2e, {co2_summary_data['total_energy_mwh']:.2f} mWh")
                else:
                    typer.echo(f"  ⚠ Failed to submit CO2 summary: {response.text}", err=True)
        
        # Summary for this run
        has_bco = "✓" if bco_file else "✗"
        has_co2 = "✓" if co2_trace else "✗"
        typer.echo(f"  Summary: BCO={has_bco}, CO2={has_co2}, Processes={len(process_execution_data)}")
    
    # Trigger manual retraining if requested
    if retrain:
        typer.echo("\n🔄 Triggering manual model retraining...")
        response = requests.post(
            f"{API_BASE_URL}/ml/retrain",
            json={"prioritize_failures": True},
            headers=headers
        )
        
        if response.status_code == 200:
            result = response.json()
            typer.echo(f"  ✓ Retraining complete!")
            typer.echo(f"    - Training samples: {result.get('training_samples', 0)}")
            typer.echo(f"    - Failure samples: {result.get('failure_samples', 0)}")
            typer.echo(f"    - Prioritized failures: {result.get('prioritized_failures', False)}")
            
            # Show failure notification if failures were found
            if result.get('failure_samples', 0) > 0:
                typer.echo(f"\n⚠️  {result['failure_samples']} failure data points detected - models weighted 2x higher for these samples")
        else:
            typer.echo(f"  ✗ Retraining failed: {response.text}", err=True)

if __name__ == "__main__":
    app()