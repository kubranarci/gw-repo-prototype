# gw-repo-prototype
An API prototype for storing provenance and resource usage information from Nextflow workflow executions, equipped with a Streamlit analytics dashboard.

## API Deployment

Add a `.env` file to `api/` with these variable definitions:

```bash
API_KEY='add-the-desired-api-key-here'
DATABASE_URL='postgresql://postgres:postgres-password@db/database-name'
```

Add a `.env` file to `db/` (directory needs to be created):

```bash
POSTGRES_PASSWORD=postgres-password
POSTGRES_DB=database-name
```

Start the core backend containers:

```bash
docker compose up -d --build
```

## Client Requirements & Setup

Install the updated Python dependencies required for data extraction and visualization:

```bash
pip install typer requests python-dotenv streamlit plotly pandas
```

### Nextflow Configuration

You must enable process trace and the nf-prov plugin with BCO output in your `nextflow.config`:
```groovy
plugins {
    id 'nf-prov'
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
```

Run your SLURM or local workflows as usual. Ensure the pipeline metadata (trace and bco files) is generated in the target execution directory.

### Client Environment Configuration

Create a `.env` file in the root or `client/` directory with the following variables:

```bash
API_BASE_URL=http://localhost:80
API_KEY=your_api_key_here
```

## Submitting Execution Data

The client script has been refactored to process entire output directories containing paired execution trace and BCO files. 

Run the client to parse the metadata and submit it to the PostgreSQL database via the REST API:

```bash
python client/client.py <path_to_pipeline_info_directory> [--api-key <your_api_key>]
```

Parameters:
* `<path_to_pipeline_info_directory>`: Path to the directory containing both `.nextflow.log` / `execution_trace_*.txt` and `manifest_*.bco.json` files.
* `--api-key`: API key for authentication (optional if already exported in your environment).

## Visualization Dashboard

To inspect the resource allocations, I/O bottlenecks, and completion times of your workflows, launch the Streamlit analytics interface:

```bash
streamlit run ui/app.py
```
*(If running on a remote cluster, establish an SSH tunnel for port 8501 or bind Streamlit to `0.0.0.0` to access the dashboard from your local browser).*