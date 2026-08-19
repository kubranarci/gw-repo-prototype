# gw-repo-prototype
An API prototype for storing provenance and resource usage information from Nextflow workflow executions, equipped with a Streamlit analytics dashboard and ML-based resource optimization.

## Quick Start

```bash
./setup.sh
docker compose up -d
```

The `setup.sh` script will:
- Generate a secure API key automatically
- Create the consolidated `.env` configuration file
- Initialize the database schema

## Client Requirements & Setup

Install Python dependencies:

```bash
pip install typer requests python-dotenv streamlit plotly pandas
```

### Nextflow Configuration

**Quick Start**: Use the provided configuration file when running your workflows:

```bash
nextflow run main.nf -profile docker/singularity/conda -c path/to/gwrepo.config -c ...
```

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

Run your SLURM or local workflows as usual. Ensure the pipeline metadata (trace, bco, and co2footprint files) is generated in the target execution directory.

### Client Environment Configuration

The root `.env` file (created by `setup.sh`) contains all required variables. Export it before running the client:

```bash
export $(cat .env | xargs)
```

Or set `INSTITUTE_ID` to override the default:

```bash
export INSTITUTE_ID=DKFZ
```

INSTITUTE_ID can also be `LOCAL`, `NONE`, `UNKNOWN`

## Submitting Execution Data

The client script processes entire output directories containing execution trace, BCO, and CO2 footprint files.

Run the client to parse the metadata and submit it to the PostgreSQL database via the REST API:

```bash
python client/client.py <path_to_pipeline_info_directory> [--api-key <your_api_key>]
```

**Parameters:**
* `<path_to_pipeline_info_directory>`: Path to the directory containing:
  - `execution_trace_*.txt` (required)
  - `manifest_*.bco.json` (optional, provenance data)
  - `co2footprint_trace_*.txt` (optional, CO2 per-process data)
  - `co2footprint_summary_*.txt` (optional, CO2 workflow summary)
* `--api-key`: API key for authentication (optional if `API_KEY` is set in environment)

**Example:**
```bash
# Using API_KEY environment variable
export API_KEY=your_api_key_here
python client/client.py ./results/pipeline_info

# Or pass API key directly
python client/client.py ./results/pipeline_info --api-key your_api_key_here
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

### Model Architecture
- **Algorithm**: Gradient Boosting Regressor with 5-fold cross-validation
- **Targets**: Memory (MB), Duration (seconds), CPU utilization (cores)
- **Features**: 80+ features including resource requests, utilization metrics, I/O ratios, CO2 footprint
- **Safety Margins**: P95-based recommendations for production deployments

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