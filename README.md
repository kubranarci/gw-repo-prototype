# gw-repo-prototype
An API prototype for storing provenance and resource usage information from Nextflow workflow executions, equipped with a Streamlit analytics dashboard and ML-based resource optimization.


```
[ Nextflow Pipeline Execution ]
       │
       ├─────────────────────────┬─────────────────────────┬─────────────────────────┐
       ▼                         ▼                         ▼                         ▼
┌──────────────┐         ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│     work     │         │ co2footprint │         │   bco.json   │         │  trace.txt   │
│  directory   │         │  (trace/sum) │         │              │         │              │
└──────────────┘         └──────────────┘         └──────────────┘         └──────────────┘
       │                         │                         │                         │
       └─────────────────────────┴────────────┬────────────┴─────────────────────────┘
                                              ▼
                                 [ ETL Script and API Client ]
                                              │
                                              ▼ (HTTP POST / Bearer Token)
┌────────────────────────────────────────────────────────────────┐
│                      Centralized Service                       │
│                                                                │
│                     ┌───────────────────┐                      │
│                     │    GW RePO API    │◄──────┐              │
│                     └───────┬───┬───────┘       │              │
│       (Reads/Writes)        │   │               │ (REST API    │
│       ┌─────────────────────┘   └───────┐       │  Queries)    │
│       ▼                                 ▼       │              │
│ ┌────────────┐                  ┌──────────────┐│              │
│ │ PostgreSQL │                  │ ML Resource  ││              │
│ │  Database  │                  │    Models    ││              │
│ └────────────┘                  └──────────────┘│              │
│                                                 │              │
│                     ┌───────────────────┐       │              │
│                     │ Streamlit UI App  ├───────┘              │
│                     │   (User Facing)   │                      │
│                     └───────────────────┘                      │
└────────────────────────────────────────────────────────────────┘
```
## Documentation

- 📖 [Technical Documentation](doc/TECHNICAL_DOCS.md) - CPU recommendations, work directory scanning, API endpoints, troubleshooting
- 📝 [Changelog](CHANGELOG.md) - Recent changes and version history

## Quick Start

```bash
./setup.sh
docker compose up -d
```

The `setup.sh` script will:
- Generate a secure API key automatically
- Create the consolidated `.env` configuration file
- Initialize the database schema

## Deployment Model

**Each user runs their own isolated GW-Repo instance:**

```
Your Machine
└── Docker Compose
    ├── API Container (port 80)
    ├── PostgreSQL Database (port 5432) ← Your private database
    └── Streamlit Dashboard (port 8501)
```

**Key Points**:
- ✅ **Private**: Your workflow data stays on your machine
- ✅ **Isolated**: No sharing with other users
- ✅ **Self-contained**: Everything runs in Docker containers
- ✅ **Your data**: PostgreSQL database is yours alone
- ✅ **Your models**: ML models train only on YOUR workflow data

**Why this design?**
- Genomic workflow data is often sensitive
- Different institutes have different hardware (recommendations are environment-specific)
- Simple deployment: no central service to maintain
- Works offline, no internet required after setup

## Data Persistence

**Data is stored permanently** in a PostgreSQL Docker volume and persists across:
- `docker compose down` / `docker compose up -d`
- Container restarts
- System reboots

**Storage location**: `/var/lib/docker/volumes/gw-repo-db-data`

**To delete all data:**
```bash
docker compose down -v  # Removes the database volume
rm .env                 # Optional: remove configuration
```

**To view stored data:**
```bash
docker compose exec db psql -U postgres -d gw_repo -c "\dt"  # List tables
docker compose exec db psql -U postgres -d gw_repo -c "SELECT COUNT(*) FROM workflowexecution;"  # Count workflows
```

**Backup your data:**
```bash
# Manual backup
docker compose exec db pg_dump -U postgres gw_repo > backup-$(date +%Y%m%d).sql

# Restore from backup
docker compose exec db psql -U postgres -d gw_repo < backup-20260821.sql
```

## Client Requirements & Setup

Install Python dependencies:

```bash
pip install typer requests python-dotenv streamlit plotly pandas
```

### Nextflow Configuration

**Manual Configuration**: Enable process trace, nf-prov, and nf-co2footprint plugins in your `nextflow.config`:

```groovy
plugins {
    id 'nf-prov'             // Provenance tracking (required)
    id 'nf-co2footprint'     // CO2 emission tracking (recommended)
}

prov {
    enabled = true
    formats {
        bco {
            file = "bco-${new Date().format('yyyyMMdd')}-${System.nanoTime().toString().take(8)}.json"
        }
    }
}

trace {
    enabled = true
    fields = 'hash,process,name,status,exit,module,container,attempt,submit,start,complete,duration,cpus,time,disk,memory,realtime,queue,%cpu,%mem,peak_rss,peak_vmem,rchar,wchar'
}

co2footprint {
    trace {
        file = "./pipeline_info/co2footprint_trace-${new Date().format('yyyyMMdd')}.txt"
    }
}
```

Run your SLURM, LSF or local workflows as usual. Ensure the pipeline metadata (trace, bco, and co2footprint files) is generated in the target execution directory.

### Client Environment Configuration

The root `.env` file (created by `setup.sh`) contains all required variables. Export it before running the client:

```bash
export $(cat .env | xargs)
```

#### Institute ID (IMPORTANT)

Set `INSTITUTE_ID` to tag your workflow data. This enables **environment-specific recommendations**:

```bash
export INSTITUTE_ID=DKFZ    # DKFZ cluster
```

**Why this matters**: ML models train separately for each institute, so recommendations are tailored to your specific hardware and environment.

**Valid values**: Any string (e.g., `DKFZ`, `EMBL`, `LOCAL`, `NONE`, `UNKNOWN`, or custom institute names)

## Submitting Execution Data

The client script processes entire output directories containing execution trace, BCO, and CO2 footprint files.

Run the client to parse the metadata and submit it to the PostgreSQL database via the REST API:

```bash
export API_KEY=your_api_key_here
python client/client.py <path_to_pipeline_info_directory> [--work-dir <path_to_work_directory>] [--api-key <your_api_key>]
```

**Parameters:**
* `<path_to_pipeline_info_directory>`: Path to the directory containing:
  - `execution_trace_*.txt` (required)
  - `manifest_*.bco.json` (optional, provenance data)
  - `co2footprint_trace_*.txt` (optional, CO2 per-process data)
  - `co2footprint_summary_*.txt` (optional, CO2 workflow summary)
* `--work-dir`: Path to Nextflow work directory for disk usage scanning (optional)
* `--api-key`: API key for authentication (optional if `API_KEY` is set in environment)

When `--work-dir` is provided, the client automatically scans the work directory to extract additional metrics:

**Extracted Metrics**:
- `disk_usage_mb`: Total disk space used by task (MB)
- `read_bytes`: Bytes read from disk
- `write_bytes`: Bytes written to disk
- `peak_vmem_mb`: Peak virtual memory (MB)
- `peak_rss_mb`: Peak resident memory (MB)

**Note**: The scanner NEVER stores file paths, filenames, or sample names - only numerical values.

**Example Output**:
```
Found 1 workflow runs to process. Institute: DKFZ

--- Processing Run: 2026-08-20_14-47-55 ---
  ✓ Workflow submitted
  Scanning work directory for 145 tasks...
  ✓ Scanned 145 tasks
  ✓ Submitted 145 processes with disk metrics
```

## Visualization Dashboard

To inspect the resource allocations, I/O bottlenecks, and completion times of your workflows, launch the Streamlit analytics interface:

```bash
streamlit run ui/app.py
```

Open http://localhost:8501 in your browser.

The dashboard provides 5 pages:

### Dashboard
- Process resource utilization charts (CPU, memory, duration, I/O)
- Filter by process name
- Generate optimized Nextflow config based on historical averages
- Download detailed process data tables

### ML Training
- Train Gradient Boosting models for memory, time, and CPU prediction
- Filter training data by institute
- View model performance metrics (R², RMSE, MAE)
- Analyze feature importance rankings

### ML Predictions
- Get resource predictions for any process by name
- Includes P95 safety margins for production use
- Auto-generates Nextflow config snippets
- Download ready-to-use configuration files

### Optimization
- Data-driven recommendations based on historical executions
- Statistical analysis (mean, median, P95, max) for memory, duration, CPU, energy, and CO2
- Process insights (e.g., "CPU-bound", "I/O-bound")
- Recommended configuration with safety margins

### Model Performance
- Monitor all trained models and their accuracy metrics
- Compare model performance across different targets
- View feature importance visualizations
- Track model training history and artifacts

## ML Features

The system includes machine learning capabilities for resource prediction and optimization:

### Institute & Pipeline-Based Recommendations

**Key Concept**: Recommendations are **specific to your environment** (institute + pipeline).

```
Institute (e.g., DKFZ) + Pipeline (e.g., variantbenchmarking)
       ↓
Historical executions from YOUR environment
       ↓
ML models trained on YOUR data
       ↓
Recommendations optimized for YOUR hardware & workflows
```

**Why this matters**:
- Different institutes have different hardware (CPU models, storage speeds)
- Different pipelines have different resource patterns
- Recommendations from DKFZ may not apply to EMBL, and vice versa

**How it works**:
1. Submit workflow data with `INSTITUTE_ID` set (e.g., `DKFZ`, `EMBL`, `LOCAL`)
2. ML models train separately for each institute
3. Recommendations filter by institute automatically
4. Results are tailored to your specific environment

### Model Architecture
- **Algorithm**: Gradient Boosting Regressor with 5-fold cross-validation
- **Targets**: Memory (MB), Duration (seconds), CPU utilization (cores)
- **Features**: 80+ features including resource requests, utilization metrics, I/O ratios, CO2 footprint
- **Safety Margins**: P95-based recommendations for production deployments
- **Environment-Specific**: Models trained per-institute for hardware-aware predictions

### Training the Models

Via API:
```bash
curl -X POST http://localhost/ml/train \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"institute_id": "DKFZ"}'
```

Via UI: Navigate to "ML Training" page and click "Start Training"

**Requirements**: Minimum 100 process executions for reliable predictions (500+ recommended)

### Getting Predictions

Via API:
```bash
curl "http://localhost/ml/predict?process_name=BCFTOOLS_SORT" \
  -H "Authorization: Bearer $API_KEY"
```

Response:
```json
{
  "success": true,
  "predictions": {
    "memory": {"value": 512.5, "unit": "MB", "confidence": 0.7, "safety_margin": 1.15},
    "time": {"value": 45.2, "unit": "seconds", "confidence": 0.7, "safety_margin": 1.15},
    "cpu": {"value": 2.1, "unit": "cores", "confidence": 0.7, "safety_margin": 1.15}
  },
  "nextflow_config": {
    "memory": "512 MB",
    "time": "45s",
    "cpus": 2
  }
}
```

### Optimization Recommendations

Via API:
```bash
curl "http://localhost/ml/optimization/BCFTOOLS_SORT?institute_id=DKFZ" \
  -H "Authorization: Bearer $API_KEY"
```

Provides:
- Historical statistics (mean, std, min, max, median, P95, P99)
- Recommended configuration based on P95 values
- Process insights (CPU-bound, I/O-bound, memory-efficient, etc.)
- Energy and CO2 footprint analysis

### Model Metadata

View trained model information:
```bash
curl "http://localhost/ml/models" \
  -H "Authorization: Bearer $API_KEY"
```

Returns model types, training timestamps, accuracy metrics, and feature importance data.

### Feature Engineering

The ML module automatically extracts and engineers features including:
- **Resource requests**: CPUs, memory, time, storage
- **Utilization metrics**: CPU %, memory %, efficiency ratios
- **I/O patterns**: Read/write bytes, I/O ratio
- **CO2 footprint**: Energy consumption, carbon emissions
- **Categorical encodings**: Institute, CPU model, process type
- **Derived features**: CPU-memory product, energy per second, CO2 per MB

### Institute Support

Models can be trained per-institute for hardware-specific predictions:
- Set `INSTITUTE_ID` environment variable in client
- Filter training data by institute
- Compare resource usage across different hardware infrastructures

## Configuration

All configuration is in the root `.env` file (auto-generated by `setup.sh`):

```bash
# API Authentication
API_KEY=<auto-generated-secure-key>

# Database Configuration
DATABASE_URL=postgresql://postgres:local_dev_pass_123@db/gw_repo
POSTGRES_PASSWORD=local_dev_pass_123
POSTGRES_DB=gw_repo

# Client Configuration
API_BASE_URL=http://localhost:80
INSTITUTE_ID=DKFZ  # Options: DKFZ, EMBL, LOCAL, NONE, UNKNOWN, or custom institute name
```

To regenerate the API key, delete `.env` and run `./setup.sh` again.