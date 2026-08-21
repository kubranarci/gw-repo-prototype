from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import SQLModel, Field, create_engine, Session, Relationship, select, delete
from sqlalchemy import text
from typing import Optional, List, Annotated
from datetime import datetime, timezone
import os, time

from models import (
    Institut,
    Hardwareinventory,
    Co2footprint,
    Workflowco2summary,
    Optimizationrule,
    Mlmodelmetadata
)
import json
import numpy as np

def convert_numpy_types(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db/dbname")
engine = create_engine(DATABASE_URL, echo=True)

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise EnvironmentError("Missing API_KEY environment variable")
security = HTTPBearer()

def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key"
        )
    return credentials.credentials


class ProcessExecutionParameterInput(SQLModel, table=True):
    process_execution_id: str = Field(foreign_key="processexecution.id", primary_key=True)
    parameter_name: str = Field(primary_key=True)
    parameter_value: str

    process_execution: Optional["ProcessExecution"] = Relationship(back_populates="parameters")

class ProcessExecutionInputFile(SQLModel, table=True):
    process_execution_id: str = Field(foreign_key="processexecution.id", primary_key=True)
    filename: str = Field(primary_key=True)
    xxhash128: Optional[str] = None

    process_execution: Optional["ProcessExecution"] = Relationship(back_populates="input_files")

class ProcessExecutionOutputFile(SQLModel, table=True):
    process_execution_id: str = Field(foreign_key="processexecution.id", primary_key=True)
    filename: str = Field(primary_key=True)
    xxhash128: Optional[str] = None

    process_execution: Optional["ProcessExecution"] = Relationship(back_populates="output_files")

class WorkflowExecution(SQLModel, table=True):
    id: str = Field(primary_key=True)
    start_time: Optional[float] = None
    duration: Optional[float] = None
    run_name: Optional[str] = None
    nextflow_version: Optional[str] = None
    final_state: Optional[str] = None
    revision_id: Optional[str] = None
    institute_id: Optional[str] = Field(default="UNKNOWN", foreign_key="institut.id")

    process_executions: List["ProcessExecution"] = Relationship(back_populates="workflow_execution")
    institut: Optional["Institut"] = Relationship(back_populates="workflows")

class ProcessExecution(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workflow_execution_id: str = Field(foreign_key="workflowexecution.id")
    institute_id: Optional[str] = Field(default="UNKNOWN", foreign_key="institut.id")
    process_name: str
    module_name: Optional[str] = None
    container_name: Optional[str] = None
    final_status: str
    exit_code: int
    start_time: float
    duration: float
    cpus_requested: Optional[float] = None
    time_requested: Optional[float] = None
    storage_requested: Optional[float] = None
    memory_requested: Optional[float] = None
    realtime: float
    queue_name: Optional[str] = None
    percent_cpu: float
    percent_memory: float
    peak_rss: float
    peak_vmem: float
    read_char: float
    write_char: float
    
    # Work directory metrics (privacy-safe: ONLY numbers, no paths/filenames)
    disk_usage_mb: Optional[float] = None
    read_bytes: Optional[int] = None
    write_bytes: Optional[int] = None
    peak_vmem_mb: Optional[float] = None
    peak_rss_mb: Optional[float] = None

    workflow_execution: Optional[WorkflowExecution] = Relationship(back_populates="process_executions")
    institut: Optional["Institut"] = Relationship(back_populates="process_executions")
    parameters: List[ProcessExecutionParameterInput] = Relationship(back_populates="process_execution")
    input_files: List[ProcessExecutionInputFile] = Relationship(back_populates="process_execution")
    output_files: List[ProcessExecutionOutputFile] = Relationship(back_populates="process_execution")


app = FastAPI()

def get_session():
    with Session(engine) as session:
        yield session

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)


@app.post("/workflows/", response_model=WorkflowExecution)
def create_workflow(
    execution: WorkflowExecution, 
    session: Session = Depends(get_session), 
    api_key: str = Depends(verify_api_key)
):
    db_obj = session.merge(execution)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/workflows/", response_model=List[WorkflowExecution])
def get_workflows(session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    return session.exec(select(WorkflowExecution)).all()

@app.get("/workflows/{execution_id}", response_model=WorkflowExecution)
def get_workflow(execution_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    workflow = session.get(WorkflowExecution, execution_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow

# CO2 endpoints must come BEFORE /processes/{process_id} to avoid route conflicts
@app.post("/processes/co2", response_model=Co2footprint)
def create_process_co2_footprint(
    co2_data: Co2footprint,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Submit CO2 footprint data for a process."""
    # Verify process exists
    process = session.get(ProcessExecution, co2_data.process_execution_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    
    db_obj = session.merge(co2_data)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/processes/co2", response_model=Co2footprint)
def get_process_co2_footprint(
    process_execution_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get CO2 footprint data for a process."""
    co2_data = session.get(Co2footprint, process_execution_id)
    if not co2_data:
        raise HTTPException(status_code=404, detail="CO2 footprint not found")
    return co2_data

@app.post("/processes/", response_model=ProcessExecution)
def create_process(process: ProcessExecution, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    db_obj = session.merge(process)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/processes/", response_model=List[ProcessExecution])
def get_processes(session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    return session.exec(select(ProcessExecution)).all()

@app.get("/processes/{process_id}", response_model=ProcessExecution)
def get_process(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    process = session.get(ProcessExecution, process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    return process

@app.delete("/processes/{process_id}")
def delete_process(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    process = session.get(ProcessExecution, process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    session.delete(process)
    session.commit()
    return {"message": "Process deleted successfully"}

@app.post("/parameters/", response_model=ProcessExecutionParameterInput)
def create_parameter(param: ProcessExecutionParameterInput, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    db_obj = session.merge(param)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/parameters/{process_id}", response_model=List[ProcessExecutionParameterInput])
def get_parameters(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    result = session.exec(select(ProcessExecutionParameterInput).where(ProcessExecutionParameterInput.process_execution_id == process_id)).all()
    return result

@app.delete("/parameters/{process_id}")
def delete_parameters(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    session.exec(
        delete(ProcessExecutionParameterInput)
        .where(ProcessExecutionParameterInput.process_execution_id == process_id)
    )
    session.commit()
    return {"message": "Parameters deleted successfully"}

@app.post("/input_files/", response_model=ProcessExecutionInputFile)
def create_input_file(file: ProcessExecutionInputFile, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    db_obj = session.merge(file)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/input_files/{process_id}", response_model=List[ProcessExecutionInputFile])
def get_input_files(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    return session.exec(select(ProcessExecutionInputFile).where(ProcessExecutionInputFile.process_execution_id == process_id)).all()

@app.delete("/input_files/{process_id}")
def delete_input_files(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    session.exec(
        delete(ProcessExecutionInputFile)
        .where(ProcessExecutionInputFile.process_execution_id == process_id)
    )
    session.commit()
    return {"message": "Input files deleted successfully"}

@app.post("/output_files/", response_model=ProcessExecutionOutputFile)
def create_output_file(file: ProcessExecutionOutputFile, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    db_obj = session.merge(file)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/output_files/{process_id}", response_model=List[ProcessExecutionOutputFile])
def get_output_files(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    return session.exec(select(ProcessExecutionOutputFile).where(ProcessExecutionOutputFile.process_execution_id == process_id)).all()

@app.delete("/output_files/{process_id}")
def delete_output_files(process_id: str, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    session.exec(
        delete(ProcessExecutionOutputFile)
        .where(ProcessExecutionOutputFile.process_execution_id == process_id)
    )
    session.commit()
    return {"message": "Output files deleted successfully"}


# ==================== Institute Endpoints ====================

@app.post("/institutes/", response_model=Institut)
def create_institute(
    institute: Institut,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    db_obj = session.merge(institute)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/institutes/", response_model=List[Institut])
def get_institutes(
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    return session.exec(select(Institut)).all()

@app.get("/institutes/{institute_id}", response_model=Institut)
def get_institute(
    institute_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    institute = session.get(Institut, institute_id)
    if not institute:
        raise HTTPException(status_code=404, detail="Institute not found")
    return institute

@app.get("/institutes/{institute_id}/statistics")
def get_institute_statistics(
    institute_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get aggregated resource usage statistics for an institute."""
    # Get total workflows
    workflow_count = session.exec(
        select(WorkflowExecution)
        .where(WorkflowExecution.institute_id == institute_id)
    ).all()
    
    # Get total processes
    process_count = session.exec(
        select(ProcessExecution)
        .where(ProcessExecution.institute_id == institute_id)
    ).all()
    
    # Calculate totals
    total_duration = sum(p.duration for p in process_count if p.duration)
    total_peak_rss = sum(p.peak_rss for p in process_count if p.peak_rss)
    total_peak_vmem = sum(p.peak_vmem for p in process_count if p.peak_vmem)
    
    return {
        "institute_id": institute_id,
        "total_workflows": len(workflow_count),
        "total_processes": len(process_count),
        "total_duration_sec": total_duration,
        "total_peak_rss_mb": total_peak_rss,
        "total_peak_vmem_mb": total_peak_vmem,
    }

@app.get("/institutes/{institute_id}/co2-stats")
def get_institute_co2_stats(
    institute_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get CO2 emissions summary for an institute."""
    # Get all workflows for this institute
    workflows = session.exec(
        select(WorkflowExecution)
        .where(WorkflowExecution.institute_id == institute_id)
    ).all()
    
    workflow_ids = [w.id for w in workflows]
    
    if not workflow_ids:
        return {
            "institute_id": institute_id,
            "total_workflows": 0,
            "total_energy_mwh": 0,
            "total_co2e_mg": 0,
            "processes_with_co2_data": 0,
        }
    
    # Get CO2 summaries for workflows
    co2_summaries = session.exec(
        select(Workflowco2summary)
        .where(Workflowco2summary.workflow_execution_id.in_(workflow_ids))
    ).all()
    
    total_energy = sum(s.total_energy_mwh for s in co2_summaries)
    total_co2e = sum(s.total_co2e_mg for s in co2_summaries)
    
    return {
        "institute_id": institute_id,
        "total_workflows": len(workflows),
        "workflows_with_co2_data": len(co2_summaries),
        "total_energy_mwh": total_energy,
        "total_co2e_mg": total_co2e,
    }

@app.post("/institutes/{institute_id}/hardware", response_model=Hardwareinventory)
def add_hardware(
    institute_id: str,
    hardware: Hardwareinventory,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Register hardware for an institute."""
    # Verify institute exists
    institute = session.get(Institut, institute_id)
    if not institute:
        raise HTTPException(status_code=404, detail="Institute not found")
    
    hardware.institute_id = institute_id
    db_obj = session.merge(hardware)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/institutes/{institute_id}/hardware", response_model=List[Hardwareinventory])
def get_institute_hardware(
    institute_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get hardware inventory for an institute."""
    return session.exec(
        select(Hardwareinventory)
        .where(Hardwareinventory.institute_id == institute_id)
    ).all()


# ==================== CO2 Footprint Endpoints ====================

@app.post("/workflows/{workflow_id}/co2/", response_model=Workflowco2summary)
def create_workflow_co2_summary(
    workflow_id: str,
    co2_summary: Workflowco2summary,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Submit CO2 summary for a workflow."""
    # Verify workflow exists
    workflow = session.get(WorkflowExecution, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    co2_summary.workflow_execution_id = workflow_id
    db_obj = session.merge(co2_summary)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/workflows/{workflow_id}/co2/", response_model=Workflowco2summary)
def get_workflow_co2_summary(
    workflow_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get CO2 summary for a workflow."""
    co2_data = session.get(Workflowco2summary, workflow_id)
    if not co2_data:
        raise HTTPException(status_code=404, detail="CO2 summary not found")
    return co2_data
    return co2_data


# ==================== ML Model Endpoints ====================

@app.post("/ml/models/", response_model=Mlmodelmetadata)
def register_ml_model(
    model: Mlmodelmetadata,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Register metadata for a trained ML model."""
    db_obj = session.merge(model)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/ml/models/", response_model=List[Mlmodelmetadata])
def list_ml_models(
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """List all registered ML models."""
    return session.exec(select(Mlmodelmetadata)).all()

@app.get("/ml/models/{model_id}", response_model=Mlmodelmetadata)
def get_ml_model(
    model_id: int,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get metadata for a specific ML model."""
    model = session.get(Mlmodelmetadata, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


# ==================== Optimization Rules Endpoints ====================

@app.post("/institutes/{institute_id}/optimization-rules/", response_model=Optimizationrule)
def create_optimization_rule(
    institute_id: str,
    rule: Optimizationrule,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Create an optimization rule for an institute."""
    # Verify institute exists
    institute = session.get(Institut, institute_id)
    if not institute:
        raise HTTPException(status_code=404, detail="Institute not found")
    
    rule.institute_id = institute_id
    db_obj = session.merge(rule)
    session.commit()
    session.refresh(db_obj)
    return db_obj

@app.get("/institutes/{institute_id}/optimization-rules/", response_model=List[Optimizationrule])
def get_optimization_rules(
    institute_id: str,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get optimization rules for an institute."""
    return session.exec(
        select(Optimizationrule)
        .where(Optimizationrule.institute_id == institute_id)
    ).all()


# ==================== ML Training & Prediction Endpoints ====================

@app.post("/ml/train")
def train_ml_models(
    institute_id: Optional[str] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """
    Train ML models on historical workflow data.
    
    Args:
        institute_id: Optional institute to train on (None = all institutes)
    """
    try:
        try:
            from ml.features import extract_process_features, get_feature_statistics
            from ml.models import train_all_models, ResourcePredictor
        except ImportError as e:
            return {
                "success": False,
                "error": f"Import error: {str(e)}",
                "message": "ML module not properly installed"
            }
        
        print(f"Training ML models{'for institute ' + institute_id if institute_id else 'for all institutes'}...")
        
        # Extract features from database
        df = extract_process_features(session, institute_id)
        
        if df.empty:
            return {
                "success": False,
                "error": "No training data found",
                "message": "Submit more workflow execution data first"
            }
        
        print(f"Extracted {len(df)} process records for training")
        
        # Get feature statistics
        stats = get_feature_statistics(df)
        
        # Train models
        training_results = train_all_models(df)
        
        # Register models in database
        for model_type, metrics in training_results.items():
            if metrics.get('success', False):
                model_meta = Mlmodelmetadata(
                    model_name=f"resource_{model_type}_predictor",
                    model_version=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
                    model_type="regression",
                    target_process=model_type,
                    training_samples=metrics.get('training_samples', 0),
                    accuracy_metrics=json.dumps({
                        'test_r2': float(metrics.get('test_r2', 0)),
                        'test_rmse': float(metrics.get('test_rmse', 0)),
                        'test_mae': float(metrics.get('test_mae', 0)),
                        'cv_r2_mean': float(metrics.get('cv_r2_mean', 0)),
                    }),
                    model_artifact_path=f"/code/models/{model_type}_model.joblib"
                )
                session.add(model_meta)
        
        session.commit()
        
        return {
            "success": True,
            "message": f"Trained {len([m for m in training_results.values() if m.get('success')])} models",
            "training_samples": len(df),
            "feature_statistics": convert_numpy_types({k: v for k, v in stats.items() if k != 'process_distribution'}),
            "model_results": convert_numpy_types(training_results)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Training failed - check server logs"
        }


def extract_module_name(process_name: str) -> str:
    """
    Extract clean module name from process name.
    
    Examples:
        NFCORE:...:TABIX_BGZIPTABIX_GT (test12) -> TABIX_BGZIPTABIX_GT
        NFCORE:...:BCFTOOLS_FILTER_QUERY_FP (test1) -> BCFTOOLS_FILTER_QUERY_FP
        NFCORE:...:BCFTOOLS_NORM (test1) -> BCFTOOLS_NORM
    """
    # Remove the (instance) part
    base = process_name.split(' (')[0] if ' (' in process_name else process_name
    # Get the module name (last part after colon)
    if ':' in base:
        module = base.split(':')[-1]
    else:
        module = base
    
    # Only remove numeric instance suffixes like _1, _2
    # Keep descriptive suffixes like _FILTER, _QUERY, _FP, _TP, etc.
    if module.endswith('_1') or module.endswith('_2'):
        module = module[:-2]
    
    return module


def format_memory(mb_value: float) -> str:
    """
    Format memory to human-readable values.
    Uses MB for values < 1024, GB for larger values.
    """
    if mb_value <= 0:
        return "256 MB"
    elif mb_value <= 256:
        return "256 MB"
    elif mb_value <= 512:
        return "512 MB"
    elif mb_value < 1024:
        return "768 MB"
    elif mb_value < 2048:
        return "1 GB"
    elif mb_value < 4096:
        return "2 GB"
    elif mb_value < 8192:
        return "4 GB"
    elif mb_value < 16384:
        return "8 GB"
    elif mb_value < 32768:
        return "16 GB"
    else:
        # For very large values, round to nearest 16 GB
        gb_value = int(round(mb_value / 1024 / 16) * 16)
        return f"{gb_value} GB"


def round_time(seconds: float) -> str:
    """Round time to practical values with minimum 30 seconds."""
    if seconds <= 0:
        return "30s"
    # Apply 4x safety margin
    safe_seconds = seconds * 4
    if safe_seconds < 30:
        return "30s"
    elif safe_seconds < 60:
        return "1m"
    elif safe_seconds < 300:
        return f"{int(safe_seconds / 60) * 60}s"  # Round to nearest minute
    else:
        minutes = int(safe_seconds / 60)
        if minutes < 60:
            return f"{minutes}m"
        else:
            hours = int(minutes / 60)
            return f"{hours}h{minutes % 60}m" if minutes % 60 > 0 else f"{hours}h"


@app.get("/ml/processes")
def list_processes(
    institute_id: Optional[str] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """Get list of distinct module names for dropdown (without instance suffix)."""
    try:
        query = "SELECT DISTINCT process_name FROM processexecution"
        params = {}
        
        if institute_id:
            query += " WHERE institute_id = :institute_id"
            params['institute_id'] = institute_id
        
        query += " ORDER BY process_name"
        
        result = session.execute(text(query), params)
        # Extract unique module names (without instance suffix)
        all_processes = [row[0] for row in result]
        module_names = sorted(set(extract_module_name(p) for p in all_processes))
        
        return {
            "success": True,
            "processes": module_names,
            "count": len(module_names)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "processes": []
        }


@app.get("/ml/predict")
def predict_resources(
    process_name: str,
    institute_id: Optional[str] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """
    Get ML-based resource predictions for a process using historical data.
    
    Args:
        process_name: Name of the process (e.g., "BCFTOOLS_SORT")
        institute_id: Optional institute ID to filter historical data
    """
    try:
        try:
            from ml.models import ResourcePredictor
        except ImportError as e:
            return {
                "success": False,
                "error": f"Import error: {str(e)}",
                "message": "ML module not properly installed"
            }
        
        # Load trained models
        predictor = ResourcePredictor()
        predictor.load_models()
        
        # Check if models are loaded
        if not any(predictor.models.values()):
            return {
                "success": False,
                "error": "No trained models available",
                "message": "Train models first using POST /ml/train"
            }
        
        # Get historical data for this module (extract base module name, ignore instance suffix)
        # Match processes where the module name matches (before the parentheses)
        query = """
        SELECT 
            AVG(p.cpus_requested) as cpus_requested,
            AVG(p.time_requested) as time_requested,
            AVG(p.memory_requested) as memory_requested,
            AVG(p.realtime) as realtime,
            AVG(p.percent_cpu) as percent_cpu,
            AVG(p.percent_memory) as percent_memory,
            AVG(p.peak_rss) as peak_rss,
            AVG(p.peak_vmem) as peak_vmem,
            AVG(p.read_char) as read_char,
            AVG(p.write_char) as write_char,
            AVG(p.duration) as duration,
            AVG(p.memory_requested) as memory_requested_mb,
            AVG(c.energy_consumption_mwh) as energy_consumption_mwh,
            AVG(c.co2e_mg) as co2e_mg,
            AVG(c.powerdraw_cpu_w) as powerdraw_cpu_w,
            MAX(p.institute_id) as institute_id,
            MAX(p.process_name) as process_name_full,
            COUNT(*) as sample_count
        FROM processexecution p
        LEFT JOIN co2footprint c ON p.id = c.process_execution_id
        WHERE UPPER(SPLIT_PART(p.process_name, ' (', 1)) LIKE UPPER(:process_name)
           OR UPPER(SPLIT_PART(p.process_name, ':', -1)) LIKE UPPER(:process_name)
        """
        params = {"process_name": f"%{process_name}%"}
        
        if institute_id:
            query += " AND p.institute_id = :institute_id"
            params["institute_id"] = institute_id
        
        result = session.execute(text(query), params)
        row = result.first()
        
        if not row or row.sample_count == 0:
            return {
                "success": False,
                "error": "No historical data found for this process",
                "message": "Submit more workflow data or try a different process name"
            }
        
        # Build feature vector from historical averages
        features = {
            'cpus_requested': row.cpus_requested or 0,
            'time_requested': row.time_requested or 0,
            'storage_requested': 0,
            'memory_requested': row.memory_requested or 0,
            'realtime': row.realtime or 0,
            'percent_cpu': row.percent_cpu or 0,
            'percent_memory': row.percent_memory or 0,
            'peak_rss': row.peak_rss or 0,
            'peak_vmem': row.peak_vmem or 0,
            'read_char': row.read_char or 0,
            'write_char': row.write_char or 0,
            'duration': row.duration or 0,
            'energy_consumption_mwh': row.energy_consumption_mwh or 0,
            'co2e_mg': row.co2e_mg or 0,
            'powerdraw_cpu_w': row.powerdraw_cpu_w or 0,
            'has_module': 1 if ':' in process_name else 0,
            'cpu_utilization': (row.percent_cpu or 0) / 100.0,
            'memory_utilization': (row.percent_memory or 0) / 100.0,
            'memory_requested_mb': row.memory_requested or 0,
            'memory_efficiency': (row.peak_rss or 0) / max(row.memory_requested or 1, 1),
            'time_efficiency': (row.realtime or 0) / max(row.duration or 1, 1),
            'io_total': (row.read_char or 0) + (row.write_char or 0),
            'io_ratio': (row.read_char or 0) / max((row.write_char or 1), 1),
            'cpu_mem_product': (row.percent_cpu or 0) * (row.peak_rss or 0),
            'energy_per_sec': (row.energy_consumption_mwh or 0) / max(row.duration or 1, 1),
            'co2_per_mb': (row.co2e_mg or 0) / max(row.peak_rss or 1, 1),
            'process_base': row.process_name_full.split('_')[-1].split()[0] if '_' in (row.process_name_full or '') else (row.process_name_full or process_name).split()[0],
            'institute_encoded': 0,
            'cpu_encoded': 0,
        }
        
        # Encode institute
        institute_map = {'UNKNOWN': 0, 'LOCAL': 1, 'NONE': 2, 'DKFZ': 3, 'EMBL': 4}
        features['institute_encoded'] = institute_map.get(row.institute_id or 'UNKNOWN', 0)
        
        # Use clean module name for response
        module_name = extract_module_name(row.process_name_full or process_name)
        
        # Get predictions for all resource types
        predictions = {}
        
        for resource_type in ['memory', 'time', 'cpu']:
            result = predictor.predict(features, resource_type)
            if result.get('success'):
                predictions[resource_type] = {
                    'value': result['prediction_with_safety'],
                    'unit': 'MB' if resource_type == 'memory' else ('seconds' if resource_type == 'time' else 'cores'),
                    'confidence': result['confidence'],
                    'safety_margin': result['safety_margin'],
                }
        
        # Calculate CPU from historical data
        # Use actual average when available, only cap at reasonable maximum (16 CPUs)
        avg_cpus_requested = row.cpus_requested
        avg_percent_cpu = row.percent_cpu or 0
        
        if avg_cpus_requested and avg_cpus_requested > 0:
            # Use historical average, cap at 16 for very parallel tools
            recommended_cpus = min(16, max(1, int(round(avg_cpus_requested))))
        elif avg_percent_cpu > 0:
            # Estimate from percent_cpu (e.g., 800% = ~8 cores utilized)
            # Cap at 16 for highly parallel tools
            estimated_cpus = int(round(avg_percent_cpu / 100))
            recommended_cpus = min(16, max(1, estimated_cpus))
        else:
            recommended_cpus = 1
        
        # Generate Nextflow config recommendation with safe values
        config_recommendation = {}
        if 'memory' in predictions:
            config_recommendation['memory'] = format_memory(predictions['memory']['value'] * 1.5)
        if 'time' in predictions:
            config_recommendation['time'] = round_time(predictions['time']['value'])
        config_recommendation['cpus'] = recommended_cpus
        
        return {
            "success": True,
            "module_name": module_name,
            "historical_samples": int(row.sample_count),
            "predictions": predictions,
            "nextflow_config": config_recommendation,
            "message": "Predictions based on historical data with P95 safety margin"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "message": "Prediction failed - models may not be trained"
        }


@app.get("/ml/optimization/{process_name}")
def get_optimization_recommendations(
    process_name: str,
    institute_id: Optional[str] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """
    Get optimization recommendations for a specific module.
    Combines ML predictions with historical data analysis.
    """
    try:
        # Get historical data for this module (match module name, ignore instance suffix)
        query_str = """
        SELECT 
            p.peak_rss, p.peak_vmem, p.duration, p.cpus_requested,
            p.percent_cpu, p.percent_memory, p.time_requested, p.memory_requested,
            c.energy_consumption_mwh, c.co2e_mg,
            p.process_name
        FROM processexecution p
        LEFT JOIN co2footprint c ON p.id = c.process_execution_id
        WHERE UPPER(SPLIT_PART(p.process_name, ' (', 1)) LIKE UPPER(:process_name)
           OR UPPER(SPLIT_PART(p.process_name, ':', -1)) LIKE UPPER(:process_name)
        """
        
        if institute_id:
            query_str += " AND p.institute_id = :institute_id"
        
        result = session.execute(
            text(query_str),
            {"process_name": f"%{process_name}%", "institute_id": institute_id or "UNKNOWN"}
        )
        
        historical_data = [dict(row._mapping) for row in result]
        
        if not historical_data:
            return {
                "success": False,
                "message": f"No historical data found for module: {process_name}",
                "recommendation": "Submit more workflow data first"
            }
        
        # Calculate statistics
        import numpy as np
        
        def calc_stats(values):
            values = [v for v in values if v is not None and v > 0]
            if not values:
                return None
            return {
                'mean': np.mean(values),
                'std': np.std(values),
                'min': np.min(values),
                'max': np.max(values),
                'median': np.median(values),
                'p95': np.percentile(values, 95),
                'p99': np.percentile(values, 99),
                'count': len(values)
            }
        
        # Get clean module name
        module_name = extract_module_name(process_name)
        
        # Calculate stats first
        mem_stats = calc_stats([r['peak_rss'] for r in historical_data])
        dur_stats = calc_stats([r['duration'] for r in historical_data])
        
        # Calculate average CPUs from historical data
        # Strategy: Trust explicit cpus_requested, only cap uncertain estimates
        avg_cpus = []
        has_explicit_cpu_data = False
        
        for r in historical_data:
            if r.get('cpus_requested') and r['cpus_requested'] > 0:
                # Trust explicit CPU requests from workflow - no artificial cap
                # If user requested 16 CPUs for STAR, we honor that
                avg_cpus.append(r['cpus_requested'])
                has_explicit_cpu_data = True
            elif r.get('percent_cpu') and r['percent_cpu'] > 0:
                # Estimate from percent_cpu only when explicit data unavailable
                # Cap at 12 for estimates (uncertain data needs conservative bound)
                estimated = min(12, max(1, int(round(r['percent_cpu'] / 100))))
                avg_cpus.append(estimated)
        
        # Use average - only cap if we're estimating (no explicit CPU data)
        if avg_cpus:
            avg_cpu_value = np.mean(avg_cpus)
            
            # If we have explicit CPU requests, trust them (no cap)
            # If we're estimating from percent_cpu, cap at 12 for safety
            if has_explicit_cpu_data:
                recommended_cpus = max(1, int(round(avg_cpu_value)))
            else:
                recommended_cpus = min(12, max(1, int(round(avg_cpu_value))))
        else:
            recommended_cpus = 1
        
        recommendations = {
            "module_name": module_name,
            "historical_samples": len(historical_data),
            "memory": mem_stats,
            "duration": dur_stats,
            "cpu_utilization": calc_stats([r['percent_cpu'] for r in historical_data]),
            "energy": calc_stats([r['energy_consumption_mwh'] for r in historical_data if r.get('energy_consumption_mwh')]),
            "co2": calc_stats([r['co2e_mg'] for r in historical_data if r.get('co2e_mg')]),
            "recommended_config": {
                "memory": format_memory(mem_stats['p95']) if mem_stats else "256 MB",
                "time": round_time(dur_stats['p95']) if dur_stats else "1m",
                "cpus": recommended_cpus
            }
        }
        
        # Add efficiency insights
        insights = []
        
        if recommendations['cpu_utilization']:
            avg_cpu = recommendations['cpu_utilization']['mean']
            if avg_cpu < 50:
                insights.append("Low CPU utilization - consider reducing CPU allocation")
            elif avg_cpu > 90:
                insights.append("High CPU utilization - process is CPU-bound")
        
        if recommendations['memory']:
            mem_recommended = recommendations['memory']['p95']
            mem_requested = np.mean([r['memory_requested'] for r in historical_data if r.get('memory_requested')])
            if mem_recommended < mem_recommended * 0.7:
                insights.append(f"Memory over-allocated - can reduce by ~{int((1 - mem_recommended/mem_requested)*100)}%")
        
        recommendations['insights'] = insights
        
        return {
            "success": True,
            **recommendations
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to generate recommendations"
        }


@app.get("/ml/optimizations")
def get_all_optimizations(
    institute_id: Optional[str] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """
    Get optimization recommendations for all modules at once.
    Returns a downloadable list of all process optimizations.
    """
    try:
        # Get all distinct module names
        query_modules = "SELECT DISTINCT process_name FROM processexecution"
        params = {}
        
        if institute_id:
            query_modules += " WHERE institute_id = :institute_id"
            params['institute_id'] = institute_id
        
        result = session.execute(text(query_modules), params)
        all_processes = [row[0] for row in result]
        module_names = sorted(set(extract_module_name(p) for p in all_processes))
        
        all_optimizations = []
        
        for module_name in module_names:
            # Get historical data for this module
            query_str = """
            SELECT 
                p.peak_rss, p.peak_vmem, p.duration, p.cpus_requested,
                p.percent_cpu, p.percent_memory, p.time_requested, p.memory_requested,
                c.energy_consumption_mwh, c.co2e_mg,
                COUNT(*) as sample_count
            FROM processexecution p
            LEFT JOIN co2footprint c ON p.id = c.process_execution_id
            WHERE (UPPER(SPLIT_PART(p.process_name, ' (', 1)) LIKE UPPER(:process_name)
               OR UPPER(SPLIT_PART(p.process_name, ':', -1)) LIKE UPPER(:process_name))
            """
            
            opt_params = {"process_name": f"%{module_name}%"}
            if institute_id:
                query_str += " AND p.institute_id = :institute_id"
                opt_params["institute_id"] = institute_id
            
            query_str += """
            GROUP BY p.peak_rss, p.peak_vmem, p.duration, p.cpus_requested,
                     p.percent_cpu, p.percent_memory, p.time_requested, p.memory_requested,
                     c.energy_consumption_mwh, c.co2e_mg
            """
            
            result = session.execute(text(query_str), opt_params)
            historical_data = [dict(row._mapping) for row in result]
            
            if not historical_data:
                continue
            
            import numpy as np
            
            def calc_stats(values):
                values = [v for v in values if v is not None and v > 0]
                if not values:
                    return None
                return {
                    'mean': float(np.mean(values)),
                    'median': float(np.median(values)),
                    'p95': float(np.percentile(values, 95)),
                    'min': float(np.min(values)),
                    'max': float(np.max(values)),
                    'count': len(values)
                }
            
            mem_stats = calc_stats([r['peak_rss'] for r in historical_data])
            dur_stats = calc_stats([r['duration'] for r in historical_data])
            
            # Calculate average CPUs from historical data
            # Strategy: Trust explicit cpus_requested, only cap uncertain estimates
            avg_cpus = []
            has_explicit_cpu_data = False
            
            for r in historical_data:
                if r.get('cpus_requested') and r['cpus_requested'] > 0:
                    # Trust explicit CPU requests from workflow - no artificial cap
                    # If user requested 16 CPUs for STAR, we honor that
                    avg_cpus.append(r['cpus_requested'])
                    has_explicit_cpu_data = True
                elif r.get('percent_cpu') and r['percent_cpu'] > 0:
                    # Estimate from percent_cpu only when explicit data unavailable
                    # Cap at 12 for estimates (uncertain data needs conservative bound)
                    estimated = min(12, max(1, int(round(r['percent_cpu'] / 100))))
                    avg_cpus.append(estimated)
            
            # Use average - only cap if we're estimating (no explicit CPU data)
            if avg_cpus:
                avg_cpu_value = np.mean(avg_cpus)
                
                # If we have explicit CPU requests, trust them (no cap)
                # If we're estimating from percent_cpu, cap at 12 for safety
                if has_explicit_cpu_data:
                    recommended_cpus = max(1, int(round(avg_cpu_value)))
                else:
                    recommended_cpus = min(12, max(1, int(round(avg_cpu_value))))
            else:
                recommended_cpus = 1
            
            optimization = {
                "module_name": module_name,
                "historical_samples": len(historical_data),
                "memory": mem_stats,
                "duration": dur_stats,
                "cpu_utilization": calc_stats([r['percent_cpu'] for r in historical_data]),
                "recommended_config": {
                    "memory": format_memory(mem_stats['p95']) if mem_stats else "256 MB",
                    "time": round_time(dur_stats['p95']) if dur_stats else "1m",
                    "cpus": recommended_cpus
                }
            }
            
            # Add insights
            insights = []
            if optimization['cpu_utilization'] and optimization['cpu_utilization']['mean'] < 50:
                insights.append("Low CPU utilization - consider reducing CPU allocation")
            elif optimization['cpu_utilization'] and optimization['cpu_utilization']['mean'] > 90:
                insights.append("High CPU utilization - process is CPU-bound")
            
            optimization['insights'] = insights
            all_optimizations.append(optimization)
        
        return {
            "success": True,
            "modules": len(all_optimizations),
            "optimizations": all_optimizations
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "optimizations": []
        }