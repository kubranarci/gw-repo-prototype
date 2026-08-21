# GW-Repo Documentation

This directory contains technical documentation for GW-Repo features and implementation details.

---

## Table of Contents

1. [CPU Recommendation Strategy](#cpu-recommendation-strategy)
2. [Work Directory Scanning](#work-directory-scanning)
3. [Database Schema](#database-schema)
4. [API Endpoints](#api-endpoints)

---

## CPU Recommendation Strategy

### Core Principle

**Trust explicit workflow data, cap uncertain estimates**

| Data Type | Source | Cap Applied | Rationale |
|-----------|--------|-------------|-----------|
| **Explicit** | `cpus_requested` from workflow | ❌ NO CAP | Workflow authors configured this deliberately |
| **Estimated** | `percent_cpu` utilization | ✅ Cap at 12 | Uncertain data needs conservative bounds |

### Implementation Logic

```python
# For each historical execution
if cpus_requested exists and > 0:
    avg_cpus.append(cpus_requested)  # Trust explicit
    has_explicit_cpu_data = True
elif percent_cpu exists and > 0:
    estimated = min(12, int(round(percent_cpu / 100)))
    avg_cpus.append(estimated)  # Cap estimates

# Final recommendation
if has_explicit_cpu_data:
    recommended_cpus = round(mean(avg_cpus))  # NO CAP
else:
    recommended_cpus = min(12, round(mean(avg_cpus)))  # Cap estimates
```

### Why 12 CPU Cap for Estimates?

CPU utilization (`percent_cpu`) is a noisy signal:
- Single-threaded tools can show >100% during I/O waits
- Poorly optimized tools may not benefit from more cores
- Transient spikes can skew averages

**12 CPUs** is chosen because:
- ✅ Supports most genuinely parallel tools (STAR: 12-16, Hisat2: 8-12, GATK: 4-12)
- ✅ Provides headroom for estimation errors
- ✅ Prevents runaway allocations from outliers

### Examples

#### Example 1: STAR Alignment (Truly Parallel Tool)

**Historical Data**:
```
Run 1: cpus_requested=16, percent_cpu=1580%
Run 2: cpus_requested=16, percent_cpu=1620%
Run 3: cpus_requested=16, percent_cpu=1590%
```

**Result**: `recommended_cpus = 16` (no cap - trusted explicit data)

#### Example 2: BCFTOOLS Filter (Lightly Parallel)

**Historical Data**:
```
Run 1: cpus_requested=2, percent_cpu=180%
Run 2: cpus_requested=2, percent_cpu=195%
Run 3: cpus_requested=3, percent_cpu=280%
```

**Result**: `recommended_cpus = 2` (trusted explicit data)

#### Example 3: Unknown Tool (No CPU Data)

**Historical Data**:
```
Run 1: cpus_requested=null, percent_cpu=85%
Run 2: cpus_requested=null, percent_cpu=92%
Run 3: cpus_requested=null, percent_cpu=78%
```

**Result**: `recommended_cpus = 1` (estimated and capped)

### How to Get Higher Recommendations (>12 CPUs)

If your tool genuinely needs more than 12 CPUs, add explicit CPU requests to your workflow:

```groovy
// Nextflow config
process STAR_ALIGN {
    cpus 24
    memory '64 GB'
}
```

The system will recommend **24 CPUs** (no cap - trusted explicit request).

---

## Work Directory Scanning

### Overview

Privacy-safe work directory scanner that extracts **ONLY numerical metrics** (sizes, bytes) - NO paths, NO filenames, NO sample data.

### Privacy Guarantee

**NEVER stores**:
- ❌ File paths
- ❌ Filenames  
- ❌ Sample names (HG008, test1, etc.)
- ❌ Content data

**ONLY stores**:
- ✅ Disk usage in MB (number)
- ✅ Read/write bytes (numbers)
- ✅ Peak memory in MB (numbers)

### Usage

```bash
python client/client.py /runs/pipeline_info2 \
    --work-dir /runs/work \
    --api-key ${API_KEY}
```

### Extracted Metrics

| Metric | Source | Unit | Privacy |
|--------|--------|------|---------|
| `disk_usage_mb` | File sizes | MB | ✅ Safe |
| `read_bytes` | .command.trace | bytes | ✅ Safe |
| `write_bytes` | .command.trace | bytes | ✅ Safe |
| `peak_vmem_mb` | .command.trace | MB | ✅ Safe |
| `peak_rss_mb` | .command.trace | MB | ✅ Safe |

### How It Works

1. **Parse execution trace** → Get task hashes (e.g., `07/dc0d09`)
2. **Find work directory** → `work/07/dc0d094df58e84a74387c723f00064/`
3. **Extract metrics** → `.command.trace` + file sizes
4. **Submit to API** → Only numerical values

### Example Output

```
Found 1 workflow runs to process. Institute: DKFZ

--- Processing Run: 2026-08-20_14-47-55 ---
  ✓ Workflow submitted
  Scanning work directory for 145 tasks...
  ✓ Scanned 145 tasks
  ✓ Submitted 145 processes with disk metrics
```

### Hash Matching Algorithm

Execution trace uses truncated hash: `07/dc0d09`
- First part (`07`): Directory prefix
- Second part (`dc0d09`): Hash prefix (6-8 chars)

Work directory uses full hash: `dc0d094df58e84a74387c723f00064` (32 chars)

Scanner matches by:
1. Go to directory: `work/07/`
2. Find directory starting with: `dc0d09...`
3. Use first match (should be unique)

---

## Database Schema

### ProcessExecution Table

```sql
CREATE TABLE processexecution (
    -- Core fields
    id                    VARCHAR PRIMARY KEY,
    workflow_execution_id VARCHAR REFERENCES workflowexecution(id),
    institute_id          VARCHAR REFERENCES institut(id),
    process_name          VARCHAR NOT NULL,
    module_name           VARCHAR,
    container_name        VARCHAR,
    final_status          VARCHAR NOT NULL,
    exit_code             INTEGER NOT NULL,
    start_time            DOUBLE PRECISION NOT NULL,
    duration              DOUBLE PRECISION NOT NULL,
    
    -- Resource requests
    cpus_requested        DOUBLE PRECISION,
    time_requested        DOUBLE PRECISION,
    storage_requested     DOUBLE PRECISION,
    memory_requested      DOUBLE PRECISION,
    
    -- Resource utilization
    realtime              DOUBLE PRECISION NOT NULL,
    queue_name            VARCHAR,
    percent_cpu           DOUBLE PRECISION NOT NULL,
    percent_memory        DOUBLE PRECISION NOT NULL,
    peak_rss              DOUBLE PRECISION NOT NULL,
    peak_vmem             DOUBLE PRECISION NOT NULL,
    read_char             DOUBLE PRECISION NOT NULL,
    write_char            DOUBLE PRECISION NOT NULL,
    
    -- Work directory metrics (privacy-safe)
    disk_usage_mb         DOUBLE PRECISION,
    read_bytes            BIGINT,
    write_bytes           BIGINT,
    peak_vmem_mb          DOUBLE PRECISION,
    peak_rss_mb           DOUBLE PRECISION
);
```

---

## API Endpoints

### ML Training

```bash
# Train models
curl -X POST http://localhost/ml/train \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"institute_id": "DKFZ"}'

# Get predictions
curl "http://localhost/ml/predict?process_name=BCFTOOLS_SORT" \
  -H "Authorization: Bearer $API_KEY"

# Get optimization for single module
curl "http://localhost/ml/optimization/BCFTOOLS_FILTER" \
  -H "Authorization: Bearer $API_KEY"

# Get all optimizations
curl "http://localhost/ml/optimizations?institute_id=DKFZ" \
  -H "Authorization: Bearer $API_KEY"
```

### Response Format

```json
{
  "success": true,
  "module_name": "BCFTOOLS_FILTER",
  "historical_samples": 31,
  "recommended_config": {
    "memory": "256 MB",
    "time": "14m",
    "cpus": 3
  },
  "insights": [
    "Low CPU utilization - consider reducing CPU allocation"
  ]
}
```

---

## Testing

### Work Directory Scanner

```bash
cd /Users/w620-admin/Desktop/GHGA/gw-repo/gw-repo-prototype
python3 test_work_scanner.py
```

Expected output:
```
✓ PASS: Single Task Scan
✓ PASS: Targeted Scanning
✓ PASS: Privacy Compliance
✓ PASS: Missing Task Handling
✓ PASS: Readable Units

Total: 5/5 tests passed (100.0%)
```

### CPU Recommendations

```bash
# Test single module
curl "http://localhost/ml/optimization/BCFTOOLS_SORT" \
  -H "Authorization: Bearer $API_KEY" | jq '.recommended_config.cpus'

# Test all modules
curl "http://localhost/ml/optimizations?institute_id=DKFZ" \
  -H "Authorization: Bearer $API_KEY" | \
  jq '.optimizations[] | {module: .module_name, cpus: .recommended_config.cpus}'
```

---

## Troubleshooting

### Missing CPU/Memory Fields in UI

**Cause**: API container needs rebuild after schema changes

**Solution**:
```bash
docker-compose up -d --build api
```

### Work Directory Scan Returns 0 Tasks

**Cause**: Hash extraction bug with workflow IDs containing underscores

**Solution**: Fixed in latest version - hash extraction now handles underscores correctly

### "Integer Out of Range" Error

**Cause**: `read_bytes`/`write_bytes` values exceed INTEGER limit

**Solution**:
```sql
ALTER TABLE processexecution 
ALTER COLUMN read_bytes TYPE BIGINT,
ALTER COLUMN write_bytes TYPE BIGINT;
```

### Recommended CPUs Too High/Low

**Cause**: Insufficient historical data or no explicit CPU requests

**Solution**:
1. Add explicit `cpus_requested` to workflow config
2. Run workflow 5+ times for stable recommendations
3. Check for outliers in CPU utilization

---

## Version History

### [2026-08-20] - Work Directory Integration & CPU Fix

**Added**:
- Work directory scanning (privacy-safe disk usage tracking)
- New fields: `disk_usage_mb`, `read_bytes`, `write_bytes`, `peak_vmem_mb`, `peak_rss_mb`
- Smart CPU capping (trust explicit data, cap estimates at 12)

**Fixed**:
- Hash extraction for workflow IDs with underscores
- SQL syntax error in `/ml/optimizations` endpoint
- Database schema (BIGINT for byte fields)
- Inconsistent CPU caps between endpoints

**Changed**:
- CPU recommendation: Cap at 12 for estimates, no cap for explicit data
- Documentation consolidated in `doc/` directory

### [2026-08-19] - Consolidated Configuration

**Added**:
- Single `.env` file at project root
- Auto-generated API key
- Setup script

---

## Contributing

### Code Style

- Use type hints for function signatures
- Follow existing naming conventions
- Add docstrings for public functions
- Write tests for new features

### Testing

Before submitting changes:
```bash
# Run tests
python3 test_work_scanner.py

# Verify API endpoints
curl http://localhost/ml/optimizations?institute_id=DKFZ \
  -H "Authorization: Bearer $API_KEY"

# Check database schema
docker-compose exec db psql -U postgres -d gw_repo -c "\d processexecution"
```

### Documentation

- Update this file for major features
- Keep examples concise and runnable
- Include troubleshooting tips
