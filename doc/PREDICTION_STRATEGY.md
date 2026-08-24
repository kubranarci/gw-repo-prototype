# Resource Prediction Strategy

## Critical Insight: Different Resources Have Different Meanings

The previous approach treated CPU, Memory, and Time identically (all P95), but this is fundamentally wrong. Each resource has different semantics and requires different prediction strategies.

---

## Resource-Specific Strategies

### 1. **MEMORY: P95 (Conservative)**

**Purpose**: Avoid Out-Of-Memory (OOM) kills

**Consequences**:
- Under-allocation → Job fails immediately (catastrophic)
- Over-allocation → Wasted resources (acceptable)

**Strategy**:
- Train on `peak_rss` (actual memory used)
- Predict **P95** (95th percentile)
- Safety margin: P95/Mean ratio (data-driven)

**Features Used**:
- `peak_rss`: Actual memory used (primary target)
- `memory_requested`: Historical requests (context)
- `disk_usage_mb`: Data size (larger data = more memory)
- `io_total`: I/O intensity (I/O bound = less memory pressure)

**Example**:
- Mean: 500 MB, P95: 750 MB → Recommend 750 MB
- Better to waste 250 MB than fail

---

### 2. **TIME: P95 + P99 + Minimum 1 Hour (EXTREMELY Conservative)**

**Purpose**: Avoid timeout kills - this is a KILL LIMIT

**Consequences**:
- Under-allocation → Job killed mid-execution (catastrophic, wastes all compute)
- Over-allocation → Job waits longer in queue (acceptable)

**Strategy**:
- Train on `duration` (actual runtime)
- Train **BOTH P95 and P99 models** (user can choose risk tolerance)
- Weight timeout failures **5x higher** during training
- **Enforce minimum 1 hour (3600s)** at prediction time
- **Scale minimum with data size**:
  - <10GB: 1 hour minimum
  - 10-100GB: 2 hour minimum
  - >100GB: 4 hour minimum

**Features Used**:
- `duration`: Actual runtime (primary target)
- `disk_usage_mb`: Data size (larger data = more time)
- `read_bytes`/`write_bytes`: I/O intensity (I/O bound = slower)
- `percent_cpu`: Parallelism (more cores = faster)
- `peak_rss`: Memory pressure (swapping = slower)

**Example**:
- Mean: 30 min, P95: 45 min, P99: 55 min → Recommend 1 hour (minimum)
- Mean: 2 hours, P95: 3 hours, P99: 4 hours → Recommend 4 hours
- Mean: 10 hours, P95: 18 hours, P99: 24 hours → Recommend 24 hours

**Why Both P95 and P99?**
- P95: For development/testing (faster iteration, some timeouts acceptable)
- P99: For production (maximum reliability)
- UI shows both so users can choose

---

### 3. **CPU: P75 (Efficient Utilization)**

**Purpose**: Optimal resource utilization (70-90% per-core)

**CRITICAL UNDERSTANDING**: `percent_cpu` from Nextflow trace = (CPU_time / realtime) × 100

- **100%** = 1 core fully utilized for entire runtime
- **400%** = 4 cores fully utilized (or equivalent parallel work)
- **50%** = 1 core at 50% utilization (idle half the time)

**Consequences**:
- Under-allocation → Job runs slower (performance issue)
- Over-allocation → Wasted CPU slots (efficiency issue, doesn't kill job)

**Key Insight**: CPU needs depend on the **relationship between requested and used**:

| Requested | Used (percent_cpu) | Per-Core Util | Problem | Solution |
|-----------|-------------------|---------------|---------|----------|
| 4 cores   | 200% (50% each)   | 50%           | Over-allocated | Recommend 2 cores |
| 1 core    | 150%              | 150%          | Under-allocated | Recommend 2 cores |
| 2 cores   | 180% (90% each)   | 90%           | Optimal | Keep 2 cores |
| 8 cores   | 400% (50% each)   | 50%           | Over-allocated | Recommend 4 cores |

**Strategy**:
- Train target: Optimal cores for 70-90% per-core utilization
- If `per_core_util < 30%`: Severely over-allocated → Recommend `ceil(actual_cores_used)`
- If `per_core_util 30-70%`: Moderately over-allocated → Recommend `ceil(actual_cores_used * 1.2)`
- If `per_core_util > 95%`: Under-allocated → Recommend `ceil(actual_cores_used) + 1`
- If `per_core_util 70-95%`: Optimal → Recommend `ceil(actual_cores_used)`
- Predict **P75** (75th percentile - moderate, not aggressive)

**Features Used**:
- `percent_cpu`: Actual parallelism achieved (PRIMARY - ground truth)
- `cpus_requested`: Historical requests (context, not target)
- `duration`: Runtime (long jobs may benefit from more cores)
- `disk_usage_mb`: Data size (larger data may scale with cores)
- `io_total`: I/O intensity (I/O bound = can't use more cores)
- `peak_rss`: Memory pressure (high memory = may limit parallelism)

**Why P75 not P95?**
- P95 would over-provision CPUs (waste)
- P75 gives enough headroom for 70-90% utilization
- CPU over-allocation doesn't kill jobs, just wastes resources

---

## Training Data Preparation

### CPU Target Calculation (Critical!)

```python
def estimate_cpus(row):
    percent_cpu = row['percent_cpu'] if valid else 0
    cpus_requested = row['cpus_requested'] if valid else 0
    
    if percent_cpu > 0 and cpus_requested > 0:
        actual_cores_used = percent_cpu / 100.0
        per_core_util = percent_cpu / cpus_requested
        
        if per_core_util < 50:
            # Over-allocated: reduce
            optimal_cpus = max(1, int(np.ceil(actual_cores_used)))
        elif per_core_util > 90:
            # Under-allocated: increase
            optimal_cpus = max(1, int(np.ceil(actual_cores_used)) + 1)
        else:
            # Optimal range
            optimal_cpus = max(1, int(np.ceil(actual_cores_used)))
        
        return min(16, optimal_cpus)
    elif percent_cpu > 0:
        return min(16, max(1, int(np.ceil(percent_cpu / 100))))
    elif cpus_requested > 0:
        return cpus_requested
    else:
        return 1
```

**Why this matters**:
- Old approach: Train on `cpus_requested` → learns historical mistakes
- New approach: Train on **optimal allocation** → learns efficient usage

---

## Model Architecture

### Separate Models Per Resource

| Resource | Mean Model | Percentile Models | Primary |
|----------|-----------|-------------------|---------|
| Memory   | ✓         | P95               | P95     |
| Time     | ✓         | P95, P99          | P99     |
| CPU      | ✓         | P75               | P75     |

### Failure Weighting

- Memory failures (OOM): **2x weight**
- Time failures (timeout): **5x weight** (catastrophic)
- CPU failures: **2x weight**
- Timeout detection: `failure_reason` contains "timeout", "time", "killed", "signal"

---

## Post-Processing Rules

### Time: Minimum 1 Hour
```python
time_prediction = max(model_output, 3600)  # 1 hour = 3600 seconds
```

### CPU: Integer Rounding
```python
cpu_prediction = max(1, round(model_output))
```

### Memory: No Special Rules
```python
memory_prediction = model_output  # Use as-is
```

---

## API Response Changes

### Before (all P95 - wrong):
```json
{
  "predictions": {
    "memory": {"value": 750, "value_mean": 500},
    "time": {"value": 2700, "value_mean": 1800},  // <1hr = timeout risk!
    "cpu": {"value": 4, "value_mean": 3}
  }
}
```

### After (resource-specific percentiles - correct):
```json
{
  "predictions": {
    "memory": {
      "value": 750,
      "value_mean": 500,
      "percentile_used": "P95"
    },
    "time": {
      "value": 3600,              // P99 (primary recommendation)
      "value_mean": 1800,
      "percentile_used": "P99",
      "p95": 2700,                // Also show P95 for reference
      "p99": 3600,
      "time_minimum": 3600        // Applied 1hr minimum
    },
    "cpu": {
      "value": 2,                 // P75 for efficient utilization
      "value_mean": 3,
      "percentile_used": "P75"
    }
  },
  "message": "Strategy: Memory P95 (avoid OOM), Time P99+1hr min (avoid timeout), CPU P75 (70-90% utilization)"
}
```

---

## Retraining Required

**These changes require full retraining:**

```bash
cd client
python client.py submit_directory <path> --retrain
```

Or via API:
```bash
curl -X POST http://localhost:80/ml/retrain \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json"
```

---

## Expected Improvements

### CPU Predictions:
- Before: Inconsistent (4 cores predicted, 2 cores recommended)
- After: Consistent (ML prediction = config recommendation)
- Before: Based on historical mistakes
- After: Based on optimal utilization

### Time Predictions:
- Before: Too aggressive (jobs timeout)
- After: Conservative (P99 + minimum 1 hour)
- Timeout rate: Expected to drop from ~10% to <1%

### Memory Predictions:
- Before: P95 (good)
- After: P95 (unchanged, already working)

---

## Key Files Changed

1. `api/ml/features.py` - CPU target calculation
2. `api/ml/models.py` - Different percentiles per resource
3. `api/main.py` - Use correct percentile keys
4. `ui/app.py` - Display correct percentile labels

---

## Testing Checklist

- [ ] Retrain models with new strategy
- [ ] Verify CPU predictions match config recommendations
- [ ] Verify time predictions ≥ 1 hour
- [ ] Verify no more "CPU-bound" false positives
- [ ] Check timeout rate decreases over time
- [ ] Monitor CPU utilization (target: 70-90% per-core)
