# Technical Documentation

## ML Model

**Algorithm**: Gradient Boosting Regressor

**Features (13):**
1. `has_module` - Process has module prefix
2. `disk_intensity` - Disk usage (MB)
3. `disk_io_total` - Read + write bytes (MB)
4. `disk_io_ratio` - Read/write ratio
5. `cpu_utilization` - CPU % / 100
6. `memory_utilization` - Memory % / 100
7. `io_total` - Trace I/O (MB)
8. `io_ratio` - Trace I/O ratio
9. `cpu_mem_product` - CPU × memory correlation
10. `size_category_encoded` - Small/medium/large
11. `memory_per_gb` - Memory efficiency
12. `time_per_gb` - Time efficiency
13. `cpu_per_gb` - CPU efficiency

## API Endpoints

### POST /ml/train
Train models on historical data.

```bash
curl -X POST http://localhost/ml/train \
  -H "Authorization: Bearer $API_KEY"
```

### GET /ml/predict
Get predictions for a process.

```bash
curl "http://localhost/ml/predict?process_name=BCFTOOLS_FILTER" \
  -H "Authorization: Bearer $API_KEY"
```

### GET /ml/optimizations
Get all process optimizations.

```bash
curl "http://localhost/ml/optimizations" \
  -H "Authorization: Bearer $API_KEY"
```

## Database Schema

**Key tables:**
- `workflowexecution` - Workflow runs
- `processexecution` - Process-level metrics
- `mlmodelmetadata` - Trained model info

## Troubleshooting

**Models not training:**
- Need ≥10 samples per process
- Check `docker logs gw-repo-prototype-api-1`

**Predictions all same:**
- Not enough data variation
- Collect more workflow runs with different input sizes

**API connection refused:**
```bash
docker compose restart api
```
