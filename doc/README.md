# GW-Repo Prototype - Resource Optimization Tool

## Overview

ML-powered tool for predicting and optimizing Nextflow pipeline resource requirements.

**What it does:**
- Analyzes historical workflow execution data
- Trains ML models to predict CPU, memory, and time requirements
- Generates optimized configurations for small, medium, and large datasets
- Reduces resource waste and improves pipeline efficiency

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  PostgreSQL │────▶│  FastAPI     │────▶│  Streamlit  │
│  Database   │     │  Backend     │     │  Frontend   │
└─────────────┘     └──────────────┘     └─────────────┘
```

**Components:**
- **Database**: PostgreSQL (workflow execution data)
- **API**: FastAPI (ML training & predictions)
- **UI**: Streamlit (user interface)

---

## Quick Start

### 1. Start the Application

```bash
cd gw-repo-prototype
docker-compose up -d
```

**Access Points:**
- **UI**: http://localhost:8501
- **API**: http://localhost:80

### 2. Submit Workflow Data

```bash
cd client
python client.py --api-key YOUR_API_KEY --scan
```

### 3. Train ML Models

1. Open http://localhost:8501
2. Go to **ML Training** tab
3. Click **Start Training**

### 4. Get Optimized Configurations

1. Go to **Optimizations** tab
2. Select a process from dropdown
3. View predictions for small/medium/large datasets
4. Download configuration files

---

## Usage

### Dashboard

View all historical workflow execution data:
- Detailed execution table (all runs)
- Summary statistics per process
- Resource usage visualizations

### ML Training

Train prediction models:
- Click "Start Training" button
- Models learn from historical data
- View R², RMSE, CV R² metrics

### Optimizations

Get resource predictions:
1. **Select process** from dropdown menu
2. **View predictions** for 3 dataset sizes:
   - SMALL (~10th percentile disk usage)
   - MEDIUM (~50th percentile disk usage)
   - LARGE (~90th percentile disk usage)
3. **Download configurations**:
   - `small.config` - all processes, small datasets
   - `medium.config` - all processes, medium datasets
   - `large.config` - all processes, large datasets

### Model Performance

Monitor model accuracy:
- Test R², RMSE, MAE metrics
- Cross-validation scores
- Training sample counts

---

## Configuration Files

### Output Format

Each config file contains all processes for that dataset size:

```nextflow
// small.config - SMALL dataset scenario
process {
    withName: 'BCFTOOLS_DEDUP' {
        cpus = 6
        memory = '128 MB'
        time = '1h'
    }
    withName: 'STAR_ALIGN' {
        cpus = 16
        memory = '32 GB'
        time = '4h'
    }
    // ... all other processes
}
```

### Using Configurations

```bash
# Run Nextflow with optimized config
nextflow run your_pipeline.nf -profile cluster \
  -c small.config  # or medium.config, large.config
```

---

## API Endpoints

### Training

```bash
# Train ML models
curl -X POST http://localhost:80/ml/train \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Predictions

```bash
# Get predictions for single process
curl "http://localhost:80/ml/predict?process_name=BCFTOOLS" \
  -H "Authorization: Bearer YOUR_API_KEY"

# Get predictions for all processes
curl http://localhost:80/ml/optimizations \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Model Status

```bash
# Check trained models
curl http://localhost:80/ml/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## How It Works

### 1. Data Collection

Workflow execution data is collected from Nextflow:
- `disk_usage_mb` - data size
- `peak_rss` - actual memory used
- `duration` - actual runtime
- `cpus_requested` - CPUs from config
- `percent_cpu` - actual CPU utilization

### 2. ML Training

Models learn relationships between:
- Data size → Memory requirements
- Data size → Time requirements
- CPU utilization → Optimal CPU count

**Algorithm**: Gradient Boosting Regressor
- R² > 0.99 for memory & time
- R² > 0.99 for CPU

### 3. Predictions

For each process:
1. Calculate disk usage percentiles (10th, 50th, 90th)
2. Use linear regression to scale resources
3. Apply safety margins (20% memory, 30% time)
4. Generate 3 configurations

### 4. Resource Scaling

Memory and time scale linearly with data size:

```
memory = slope × disk_size + intercept
time = slope × disk_size + intercept
```

Slopes are learned from historical data using least squares regression.

---

## Troubleshooting

### No predictions available

**Problem**: "No trained models available"

**Solution**: Train models first on ML Training tab

### All predictions show same values

**Problem**: Memory/time identical for all sizes

**Solution**: Check if historical data has varying disk sizes. Models need diverse data to learn scaling relationships.

### Training fails

**Problem**: "Training failed"

**Solution**: 
1. Ensure workflow data is submitted
2. Check API logs: `docker-compose logs api`
3. Verify minimum 10 samples per process

---

## Performance Metrics

### Model Accuracy (Typical)

| Target | Test R² | Test RMSE | Training Samples |
|--------|---------|-----------|------------------|
| Memory | 0.996+  | < 120 MB  | 1000+            |
| Time   | 0.999+  | < 1.0 s   | 1000+            |
| CPU    | 0.994+  | < 0.4     | 1000+            |

### Resource Savings

Typical improvements:
- **Memory**: 20-40% reduction vs over-provisioned configs
- **CPU**: Better utilization (50-90% vs <50%)
- **Time**: Accurate estimates reduce queue wait times

---

## Development

### Project Structure

```
gw-repo-prototype/
├── api/           # FastAPI backend
│   ├── main.py    # API endpoints
│   ├── models.py  # Database models
│   └── ml/        # ML components
│       ├── features.py
│       └── models.py
├── ui/            # Streamlit frontend
│   └── app.py
├── client/        # Data collection client
│   └── client.py
├── db/            # Database scripts
└── doc/           # Documentation
```

### Rebuild Components

```bash
# Rebuild API
docker-compose build api

# Rebuild UI
docker-compose build streamlit

# Rebuild all
docker-compose build
```

### View Logs

```bash
# API logs
docker-compose logs -f api

# UI logs
docker-compose logs -f streamlit

# Database logs
docker-compose logs -f db
```

---

## Best Practices

### Data Submission

- Submit data after each workflow run
- Ensure diverse dataset sizes for better predictions
- Include failed runs (models learn from all data)

### Model Retraining

Retrain when:
- New processes added
- R² drops below 0.9
- Predictions consistently differ from actuals
- After 100+ new workflow runs

### Configuration Selection

- **small.config**: Test runs, development, small cohorts
- **medium.config**: Typical production runs
- **large.config**: Full-scale production, large cohorts

---

## Support

For issues or questions:
1. Check logs: `docker-compose logs api`
2. Verify data submission: Dashboard tab
3. Retrain models: ML Training tab

---

## License

See LICENSE file in repository root.
