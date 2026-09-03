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


def parse_co2footprint_summary(summary_file: Path) -> Optional[Dict]:
    """
    Parse co2footprint_summary_*.txt files.
    Returns dict with workflow-level CO2 summary.
    
    Returns:
        {
            'total_energy_mwh': float,
            'total_co2e_mg': float,
            'car_km_equivalent': float,
            'tree_sequestration_time_sec': int
        }
        OR None if file doesn't exist or parsing fails
    """
    if not summary_file.exists():
        return None
    
    with open(summary_file, "r") as f:
        content = f.read()
    
    result = {}
    
    co2_match = re.search(r'CO₂e emissions:\s*([\d.]+)\s*(mg|g|ug)', content)
    if co2_match:
        value = float(co2_match.group(1))
        unit = co2_match.group(2)
        if unit == "g":
            value *= 1000
        elif unit == "ug":
            value /= 1000
        result["total_co2e_mg"] = value
    
    energy_match = re.search(r'Energy consumption:\s*([\d.]+)\s*(mWh|Wh|uWh|kWh)', content)
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
    
    car_match = re.search(r'([\d.]+[Ee]?[-+]?\d*)\s*km travelled by car', content)
    if car_match:
        try:
            result["car_km_equivalent"] = float(car_match.group(1))
        except ValueError:
            result["car_km_equivalent"] = 0.0
    
    tree_match = re.search(r'(\d+)min\s*([\d.]+)s', content)
    if tree_match:
        minutes = int(tree_match.group(1))
        seconds = float(tree_match.group(2))
        result["tree_sequestration_time_sec"] = int(minutes * 60 + seconds)
    
    if not result:
        return None
    
    result.setdefault("total_co2e_mg", 0.0)
    result.setdefault("total_energy_mwh", 0.0)
    result.setdefault("car_km_equivalent", 0.0)
    result.setdefault("tree_sequestration_time_sec", 0)
    
    return result


def parse_nextflow_log(log_file: Path) -> List[Dict]:
    """
    Parse nextflow.log and extract workflow run metrics.
    
    Format: TIMESTAMP|DURATION|RUN NAME|STATUS|REVISION ID|SESSION ID|COMMAND
    """
    if not log_file.exists():
        return []
    
    runs = []
    with open(log_file, "r") as f:
        lines = f.readlines()
    
    if len(lines) < 2:
        return []
    
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        
        timestamp_str = parts[0].strip()
        duration_str = parts[1].strip()
        run_name = parts[2].strip()
        status = parts[3].strip()
        revision_id = parts[4].strip()
        session_id = parts[5].strip()
        
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            start_time = timestamp.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        
        wall_clock_sec = duration_to_seconds(duration_str)
        
        runs.append({
            "session_id": session_id,
            "run_name": run_name,
            "start_time": start_time,
            "wall_clock_sec": wall_clock_sec,
            "status": status,
            "revision_id": revision_id,
            "timestamp_str": timestamp_str,
        })
    
    return runs


def extract_workflow_aggregates(trace_file: Path) -> Dict:
    """
    Extract workflow-level aggregates from execution_trace.txt.
    
    Returns:
        {
            'peak_cpu_percent': float (MAX),
            'peak_memory_mb': float (MAX),
            'total_io_mb': float (SUM of rchar + wchar),
            'max_concurrent_processes': int,
            'processes': List[Dict] (for concurrency calculation)
        }
    """
    if not trace_file.exists():
        return {}
    
    processes = []
    peak_cpu = 0.0
    peak_memory = 0.0
    total_io = 0.0
    
    with open(trace_file, "r") as f:
        lines = f.readlines()
    
    if len(lines) < 2:
        return {}
    
    headers = lines[0].strip().split("\t")
    
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) != len(headers):
            continue
        
        proc_data = dict(zip(headers, parts))
        
        try:
            cpu = float(proc_data.get("%cpu", "0").replace("%", ""))
            peak_cpu = max(peak_cpu, cpu)
        except (ValueError, KeyError):
            pass
        
        try:
            mem_str = proc_data.get("peak_rss", "0")
            mem_mb = parse_memory_value(mem_str)
            if mem_mb:
                peak_memory = max(peak_memory, mem_mb)
        except (ValueError, KeyError):
            pass
        
        try:
            rchar = parse_memory_value(proc_data.get("rchar", "0"))
            wchar = parse_memory_value(proc_data.get("wchar", "0"))
            if rchar:
                total_io += rchar
            if wchar:
                total_io += wchar
        except (ValueError, KeyError):
            pass
        
        try:
            start_ts = parse_trace_time(proc_data.get("start", ""))
            complete_ts = parse_trace_time(proc_data.get("complete", ""))
            if start_ts and complete_ts:
                processes.append({
                    "start": start_ts,
                    "complete": complete_ts,
                })
        except (ValueError, KeyError):
            pass
    
    max_concurrent = calculate_max_concurrent_processes(processes)
    
    return {
        "peak_cpu_percent": peak_cpu,
        "peak_memory_mb": peak_memory,
        "total_io_mb": total_io,
        "max_concurrent_processes": max_concurrent,
    }


def calculate_max_concurrent_processes(processes: List[Dict]) -> int:
    """
    Calculate max concurrent processes using sweep line algorithm.
    """
    if not processes:
        return 0
    
    events = []
    for proc in processes:
        events.append((proc["start"], 1))
        events.append((proc["complete"], -1))
    
    events.sort(key=lambda x: (x[0], x[1]))
    
    max_concurrent = 0
    current = 0
    for _, delta in events:
        current += delta
        max_concurrent = max(max_concurrent, current)
    
    return max_concurrent


def match_log_to_trace_and_co2(pipeline_info_dir: Path) -> List[Dict]:
    """
    Match nextflow.log runs with execution_trace.txt AND co2footprint_summary_*.txt files.
    
    Matching strategy:
    1. Extract timestamp from log entry
    2. Find execution_trace file with matching timestamp
    3. Find co2footprint_summary file with matching timestamp (if exists)
    4. Return combined data (CO2 fields optional)
    """
    log_file = pipeline_info_dir / "nextflow.log"
    if not log_file.exists():
        return []
    
    runs = parse_nextflow_log(log_file)
    results = []
    
    for run in runs:
        timestamp_str = run["timestamp_str"]
        date_part = timestamp_str.split(" ")[0]
        time_part = timestamp_str.split(" ")[1] if " " in timestamp_str else "00-00-00"
        time_formatted = time_part.replace(":", "-")
        
        trace_pattern = f"execution_trace_{date_part}_{time_formatted}.txt"
        trace_file = pipeline_info_dir / trace_pattern
        
        trace_data = {}
        if trace_file.exists():
            trace_data = extract_workflow_aggregates(trace_file)
        else:
            trace_files = list(pipeline_info_dir.glob("execution_trace_*.txt"))
            if trace_files:
                trace_data = extract_workflow_aggregates(trace_files[0])
        
        co2_pattern = f"co2footprint_summary_{date_part.replace('-', '')}*.txt"
        co2_files = list(pipeline_info_dir.glob(co2_pattern))
        
        co2_data = None
        if not co2_files:
            co2_files = list(pipeline_info_dir.glob("co2footprint_summary_*.txt"))
        
        if co2_files:
            co2_data = parse_co2footprint_summary(co2_files[0])
        
        result = {
            **run,
            **trace_data,
        }
        
        if co2_data:
            result.update(co2_data)
        
        results.append(result)
    
    return results


@app.command()
def submit_workflow(
    pipeline_info: str = typer.Option(..., "--pipeline-info", help="Path to pipeline_info directory"),
    nextflow_log: str = typer.Option(..., "--nextflow-log", help="Path to nextflow.log file"),
    work_dir: Optional[str] = typer.Option(None, "--work-dir", help="Path to work directory (for execution_trace files)"),
    api_key: Optional[str] = typer.Option(None, help="API key (defaults to API_KEY env var)"),
    api_url: Optional[str] = typer.Option(None, help="API base URL (defaults to API_BASE_URL env var)"),
):
    """
    Submit workflow-level metrics to GW-RePO API.
    
    Extracts metrics from nextflow.log, execution_trace.txt files, and co2footprint_summary files.
    CO2 footprint files should be inside the pipeline_info directory.
    
    Example:
        python client/client.py --pipeline-info ../runs/pipeline_info4 --nextflow-log ../runs/nextflow.log --work-dir ../runs/work2
    """
    base_url = api_url or API_BASE_URL
    key = api_key or os.getenv("API_KEY", "")
    
    pipeline_info_path = Path(pipeline_info)
    if not pipeline_info_path.exists():
        typer.echo(f"Error: Pipeline info directory not found: {pipeline_info}")
        raise typer.Exit(code=1)
    
    nextflow_log_path = Path(nextflow_log)
    if not nextflow_log_path.exists():
        typer.echo(f"Error: nextflow.log not found: {nextflow_log}")
        raise typer.Exit(code=1)
    
    typer.echo(f"Processing workflow data...")
    typer.echo(f"  Pipeline info: {pipeline_info}")
    typer.echo(f"  nextflow.log: {nextflow_log}")
    if work_dir:
        typer.echo(f"  Work directory: {work_dir}")
    
    runs = parse_nextflow_log(nextflow_log_path)
    
    if not runs:
        typer.echo("No workflow runs found in nextflow.log")
        raise typer.Exit(code=1)
    
    typer.echo(f"Found {len(runs)} workflow run(s) in nextflow.log")
    
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    submitted_count = 0
    
    for run in runs:
        timestamp_str = run["timestamp_str"]
        date_part = timestamp_str.split(" ")[0]
        time_part = timestamp_str.split(" ")[1] if " " in timestamp_str else "00-00-00"
        time_formatted = time_part.replace(":", "-")
        
        trace_data = {}
        if work_dir:
            work_path = Path(work_dir)
            trace_pattern = f"execution_trace_{date_part}_{time_formatted}.txt"
            trace_file = work_path / trace_pattern
            
            if trace_file.exists():
                trace_data = extract_workflow_aggregates(trace_file)
                typer.echo(f"  Found trace file for {run.get('run_name')}")
            else:
                trace_files = list(work_path.glob(f"execution_trace_{date_part}_*.txt"))
                if trace_files:
                    trace_data = extract_workflow_aggregates(trace_files[0])
                    typer.echo(f"  Using closest trace file for {run.get('run_name')}")
        
        co2_data = None
        co2_pattern = f"co2footprint_summary_{date_part.replace('-', '')}*.txt"
        co2_files = list(pipeline_info_path.glob(co2_pattern))
        
        if not co2_files:
            co2_files = list(pipeline_info_path.glob("co2footprint_summary_*.txt"))
        
        if co2_files:
            co2_data = parse_co2footprint_summary(co2_files[0])
            if co2_data:
                typer.echo(f"  Found CO2 data for {run.get('run_name')}")
        
        payload = {
            "session_id": run.get("session_id"),
            "run_name": run.get("run_name"),
            "start_time": run.get("start_time"),
            "wall_clock_sec": run.get("wall_clock_sec"),
            "status": run.get("status"),
            "revision_id": run.get("revision_id"),
            **trace_data,
        }
        
        if co2_data:
            payload.update(co2_data)
        
        try:
            response = requests.post(
                f"{base_url}/workflows/metrics/",
                json=payload,
                headers=headers,
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                workflow_id = result.get("id", "unknown")
                has_co2 = "✓ CO2" if co2_data else "✗"
                has_trace = "✓ trace" if trace_data else "✗"
                typer.echo(f"  ✓ {run.get('run_name')} → {workflow_id} [{has_trace}, {has_co2}]")
                submitted_count += 1
            else:
                typer.echo(f"  ✗ {run.get('run_name')}: {response.status_code}")
        except Exception as e:
            typer.echo(f"  ✗ {run.get('run_name')}: {e}")
    
    typer.echo(f"\nSuccessfully submitted {submitted_count}/{len(runs)} workflow run(s)")


if __name__ == "__main__":
    app()


