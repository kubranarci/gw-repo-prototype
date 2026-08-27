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


