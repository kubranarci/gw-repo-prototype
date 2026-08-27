"""
nf-core module name cache and normalization.

Fetches official nf-core module names from GitHub API and caches locally.
Used to normalize process names to official nf-core naming convention.
"""


import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Set


CACHE_FILE = "/code/nfcore_modules.json"
_CACHE = None
_CACHE_TIME = 0


def _load_nfcore_modules() -> Dict[str, str]:
    """Load nf-core modules from cache file or fetch from GitHub."""
    global _CACHE, _CACHE_TIME
    
    # Return cached if recent (1 hour)
    if _CACHE is not None and time.time() - _CACHE_TIME < 3600:
        return _CACHE
    
    # Try to load from cache file
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                _CACHE = json.load(f)
                _CACHE_TIME = time.time()
                return _CACHE
        except:
            pass
    
    # Fetch from GitHub
    _CACHE = _fetch_nfcore_modules()
    if _CACHE:
        try:
            Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, 'w') as f:
                json.dump(_CACHE, f, indent=2)
        except:
            pass
    _CACHE_TIME = time.time()
    return _CACHE or {}


def _fetch_nfcore_modules() -> Dict[str, str]:
    """Fetch all nf-core module names from GitHub API."""
    modules_cache = {}
    
    try:
        url = "https://api.github.com/repos/nf-core/modules/contents/modules/nf-core"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            tools_data = json.loads(response.read())
        
        tool_dirs = [d['name'] for d in tools_data if d['type'] == 'dir']
        
        for i, tool in enumerate(tool_dirs):
            try:
                tool_url = f"https://api.github.com/repos/nf-core/modules/contents/modules/nf-core/{tool}"
                tool_req = urllib.request.Request(tool_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(tool_req, timeout=30) as response:
                    submodules_data = json.loads(response.read())
                
                submodules = [d['name'] for d in submodules_data if d['type'] == 'dir']
                
                for submodule in submodules:
                    module_name = f"{tool.upper()}_{submodule.upper().replace('-', '_')}"
                    modules_cache[module_name] = f"{tool}/{submodule}"
                
                # Rate limit handling
                if i % 10 == 9:
                    time.sleep(1)
                    
            except Exception:
                continue
        
        return modules_cache
        
    except Exception:
        return {}


def normalize_module_name(process_name: str, nfcore_cache: Optional[Dict[str, str]] = None) -> str:
    """
    Normalize process name to nf-core module name (TOOL_SUBTOOL format).
    
    Only normalizes if the module exists in official nf-core/modules.
    Otherwise returns original name unchanged.
    
    Args:
        process_name: Full process name from Nextflow
        nfcore_cache: Optional pre-loaded cache
    
    Returns:
        Normalized module name (uppercase, TOOL_SUBTOOL format)
    """
    # Load nf-core modules
    if nfcore_cache is None:
        nfcore_cache = _load_nfcore_modules()
    
    # Step 1: Extract base name (remove instance suffixes)
    base = process_name.split(' (')[0] if ' (' in process_name else process_name
    
    # Step 2: Get module name 
    if ':' in base:
        module = base.split(':')[-1]
    else:
        module = base
    
    # Step 3: Convert to uppercase
    module = module.upper()
    
    # Step 4: Check if exact match in nf-core cache
    if module in nfcore_cache:
        return module
    
    # Step 5: Try progressively shorter prefixes
    parts = module.split('_')
    for i in range(len(parts), 0, -1):
        candidate = '_'.join(parts[:i])
        if candidate in nfcore_cache:
            return candidate
    
    # Step 6: No cache match - check if it's an nf-core tool pattern
    # If cache is empty (GitHub unavailable), use heuristic
    if not nfcore_cache and len(parts) >= 2:
        # Common nf-core tools (fallback when GitHub unavailable)
        KNOWN_TOOLS = {
            'HAPPY', 'TABIX', 'BCFTOOLS', 'RTGTOOLS', 'TRUVARI', 'PICARD',
            'MULTIQC', 'BEDTOOLS', 'SAMTOOLS', 'GATK', 'GATK4', 'BWA',
            'BOWTIE2', 'STAR', 'HISAT2', 'SALMON', 'KALLISTO', 'FASTQC',
            'TRIMGALORE', 'TRIMMOMATIC', 'CUTADAPT', 'MINIMAP2', 'MACS2',
            'DESEQ2', 'EDGER', 'LIMMA', 'STRINGTIE', 'RSEM', 'CELLRANGER',
            'SEURAT', 'SCANPY', 'KRAKEN2', 'KRONA', 'METAPHLAN', 'HUMANN3',
            'PROKKA', 'ROARY', 'SPADES', 'MEGAHIT', 'FLYE', 'CANU', 'MEDAKA',
            'RACON', 'PORECHOP', 'NANOPLOT', 'BUSCO', 'QUAST', 'CHECKM',
            'MANTA', 'DELLY', 'SVIM', 'SVDB', 'LUMPY', 'SURVIVOR', 'PLINK',
            'PLINK2', 'HTSLIB', 'PICARD', 'MARKDUPLICATES', 'QUALIMAP',
            'PRESEQ', 'DATAVZRD', 'AARDVARK', 'SVANALYZER', 'UCSC', 'GNU',
        }
        tool = parts[0]
        if tool in KNOWN_TOOLS:
            return f'{tool}_{parts[1]}'
    
    # Not an nf-core module - return unchanged
    return module


def get_module_display_name(module_name: str) -> str:
    """Get human-readable display name for a module."""
    return module_name.replace('_', ' ')


if __name__ == "__main__":
    print("Fetching nf-core modules...")
    modules = _load_nfcore_modules()
    print(f"Found {len(modules)} nf-core modules")
    print("\nSample modules:")
    for i, (name, path) in enumerate(sorted(modules.items())[:20]):
        print(f"  {name:40s} → {path}")
