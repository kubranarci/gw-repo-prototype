"""
Privacy-safe work directory scanner for Nextflow workflows.
Extracts ONLY numerical metrics (sizes, bytes) - NO paths, NO filenames, NO sample data.

This module scans work directories to gather disk usage and I/O metrics
while maintaining strict data protection by storing only numbers.
"""

import os
from pathlib import Path
from typing import Dict, Optional, List


def parse_command_trace(trace_file: Path) -> dict:
    """
    Parse .command.trace for resource metrics.
    Returns ONLY numerical values (already privacy-safe).
    
    Args:
        trace_file: Path to .command.trace file
        
    Returns:
        Dictionary with numerical metrics (read_bytes, write_bytes, peak_vmem, peak_rss, etc.)
    """
    metrics = {}
    if not trace_file.exists():
        return metrics
    
    try:
        with open(trace_file, 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    # Only extract numerical metrics (privacy-safe)
                    if key in ['realtime', '%cpu', '%mem', 'vmem', 'rss', 
                              'peak_vmem', 'peak_rss', 'read_bytes', 'write_bytes']:
                        try:
                            metrics[key] = float(value) if '.' in value else int(value)
                        except ValueError:
                            pass
    except (IOError, OSError):
        pass
    
    return metrics


def get_disk_usage_safe(task_dir: Path) -> dict:
    """
    Get TOTAL disk usage for a task directory.
    Returns ONLY size in MB - NO filenames, NO paths.
    
    Privacy-safe: Only returns a number (MB).
    
    Args:
        task_dir: Path to task directory
        
    Returns:
        Dictionary with disk_usage_mb (float)
    """
    total_bytes = 0
    
    try:
        for file in task_dir.rglob('*'):
            if file.is_file() and not file.name.startswith('.'):
                try:
                    total_bytes += file.stat().st_size
                except (OSError, IOError):
                    pass
    except (OSError, IOError):
        pass
    
    # Return ONLY size in MB (no filenames, no paths)
    return {
        'disk_usage_mb': round(total_bytes / (1024 * 1024), 2)
    }


def scan_task_by_hash(work_dir: Path, task_hash: str) -> Optional[dict]:
    """
    Scan a SINGLE task directory by its hash.
    work_dir/XX/{full_hash}/
    
    Returns ONLY numerical metrics (privacy-safe).
    
    Args:
        work_dir: Base work directory path
        task_hash: Task hash from execution trace (format: "XX/HASH_PREFIX")
                   e.g., "07/dc0d09" where XX=07, HASH_PREFIX=dc0d09
                   The actual directory is work/XX/dc0d094df58e84a74387c723f00064/
        
    Returns:
        Dictionary with numerical metrics or None if not found
    """
    # Handle hash format: "07/dc0d09" -> directory_prefix="07", hash_prefix="dc0d09"
    if '/' in task_hash:
        dir_prefix, hash_prefix = task_hash.split('/', 1)
    else:
        # If no slash, assume first 2 chars are directory prefix
        dir_prefix = task_hash[:2]
        hash_prefix = task_hash[2:]
    
    # The work directory structure is: work/XX/FULL_HASH/
    # where FULL_HASH starts with hash_prefix
    prefix_dir = work_dir / dir_prefix
    
    if not prefix_dir.exists():
        return None
    
    # Find directory that starts with the hash prefix
    # The full hash is typically 32 chars, but trace only shows 6-8 chars
    matching_dirs = [d for d in prefix_dir.iterdir() if d.is_dir() and d.name.startswith(hash_prefix)]
    
    if not matching_dirs:
        return None
    
    # Take first match (should be unique in practice)
    task_dir = matching_dirs[0]
    
    if not task_dir.exists():
        return None
    
    # Parse .command.trace (numerical metrics only)
    trace_file = task_dir / '.command.trace'
    trace_metrics = parse_command_trace(trace_file)
    
    # Get disk usage (size in MB only)
    disk_metrics = get_disk_usage_safe(task_dir)
    
    # Return ONLY numbers (privacy-safe)
    return {
        'disk_usage_mb': disk_metrics.get('disk_usage_mb'),
        'read_bytes': trace_metrics.get('read_bytes'),
        'write_bytes': trace_metrics.get('write_bytes'),
        'peak_vmem_mb': trace_metrics.get('peak_vmem', 0) / 1024,  # KB -> MB
        'peak_rss_mb': trace_metrics.get('peak_rss', 0) / 1024,
    }


def scan_targeted_tasks(
    work_dir: Path,
    task_hashes: List[str]
) -> Dict[str, dict]:
    """
    Scan ONLY specific tasks we care about.
    
    Args:
        work_dir: Base work directory path
        task_hashes: List of hashes from execution_trace.txt
        
    Returns:
        Dictionary: {task_hash: metrics}
        
    Privacy-safe: Returns only numerical metrics.
    """
    results = {}
    
    for task_hash in task_hashes:
        metrics = scan_task_by_hash(work_dir, task_hash)
        if metrics:
            results[task_hash] = metrics
    
    return results


def scan_work_directory(work_dir: str, task_hashes: List[str]) -> Dict[str, dict]:
    """
    Main entry point for work directory scanning.
    
    Args:
        work_dir: Path to work directory (string)
        task_hashes: List of task hashes to scan
        
    Returns:
        Dictionary: {task_hash: metrics}
        
    Example:
        >>> metrics = scan_work_directory("/path/to/work", ["954be073", "fc9cbd12"])
        >>> print(metrics["954be073"])
        {
            'disk_usage_mb': 125.5,
            'read_bytes': 52428800,
            'write_bytes': 78643200,
            'peak_vmem_mb': 13600.0,
            'peak_rss_mb': 54.8
        }
    """
    work_path = Path(work_dir)
    
    if not work_path.exists():
        print(f"Warning: Work directory does not exist: {work_dir}")
        return {}
    
    print(f"Scanning work directory for {len(task_hashes)} tasks...")
    results = scan_targeted_tasks(work_path, task_hashes)
    print(f"Successfully scanned {len(results)} tasks")
    
    return results
