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


@app.get("/ml/predict")
def predict_resources(
    process_name: str,
    institute_id: Optional[str] = None,
    input_size_mb: Optional[float] = None,
    cpus_requested: Optional[float] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    """
    Get ML-based resource predictions for a process.
    
    Args:
        process_name: Name of the process (e.g., "BCFTOOLS_SORT")
        institute_id: Optional institute ID
        input_size_mb: Optional input data size in MB
        cpus_requested: Optional requested CPUs
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
        
        # Build feature vector
        features = {
            'process_base': process_name.split('_')[-1] if '_' in process_name else process_name,
            'has_module': 1 if ':' in process_name else 0,
            'cpu_utilization': 0.5,  # Default
            'memory_utilization': 0.5,  # Default
            'io_total': input_size_mb * 1024 * 1024 if input_size_mb else 0,
            'io_ratio': 1.0,
            'cpu_mem_product': 0,
            'institute_encoded': 0,
            'cpu_encoded': 0,
        }
        
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
        
        # Generate Nextflow config recommendation
        config_recommendation = {}
        if 'memory' in predictions:
            config_recommendation['memory'] = f"{int(predictions['memory']['value'])} MB"
        if 'time' in predictions:
            config_recommendation['time'] = f"{int(predictions['time']['value'])}s"
        if 'cpu' in predictions:
            config_recommendation['cpus'] = int(predictions['cpu']['value'])
        
        return {
            "success": True,
            "process_name": process_name,
            "predictions": predictions,
            "nextflow_config": config_recommendation,
            "message": "Predictions include P95 safety margin for production use"
        }
        
    except Exception as e:
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
    Get optimization recommendations for a specific process.
    Combines ML predictions with historical data analysis.
    """
    try:
        # Get historical data for this process
        query_str = """
        SELECT 
            p.peak_rss, p.peak_vmem, p.duration, p.cpus_requested,
            p.percent_cpu, p.percent_memory, p.time_requested, p.memory_requested,
            c.energy_consumption_mwh, c.co2e_mg
        FROM processexecution p
        LEFT JOIN co2footprint c ON p.id = c.process_execution_id
        WHERE UPPER(p.process_name) LIKE UPPER(:process_name)
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
                "message": f"No historical data found for process: {process_name}",
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
        
        recommendations = {
            "process_name": process_name,
            "historical_samples": len(historical_data),
            "memory": calc_stats([r['peak_rss'] for r in historical_data]),
            "duration": calc_stats([r['duration'] for r in historical_data]),
            "cpu_utilization": calc_stats([r['percent_cpu'] for r in historical_data]),
            "energy": calc_stats([r['energy_consumption_mwh'] for r in historical_data if r.get('energy_consumption_mwh')]),
            "co2": calc_stats([r['co2e_mg'] for r in historical_data if r.get('co2e_mg')]),
            "recommended_config": {}
        }
        
        # Generate Nextflow config recommendation
        if recommendations['memory']:
            recommendations['recommended_config']['memory'] = f"{int(recommendations['memory']['p95'])} MB"
        if recommendations['duration']:
            recommendations['recommended_config']['time'] = f"{int(recommendations['duration']['p95'])}s"
        
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
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to generate recommendations"
        }