#!/usr/bin/env python3
"""
Database migration script for Phase 1 schema changes.
Safe to run multiple times (idempotent).
Auto-generates API key and .env file if not present.
"""

from sqlmodel import SQLModel, create_engine, Session, select, text
import os
import secrets
from pathlib import Path
from datetime import datetime, timezone

# Get project root (parent of api directory)
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:local_dev_pass_123@db/gw_repo")
engine = create_engine(DATABASE_URL, echo=True)


def generate_api_key():
    """Generate a secure random API key."""
    return secrets.token_urlsafe(32)


def ensure_env_file():
    """Create or update .env file with API key if not present."""
    env_content = {}
    
    # Read existing .env if present
    if ENV_FILE.exists():
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_content[key.strip()] = value.strip()
    
    # Generate API key if not present
    if "API_KEY" not in env_content:
        api_key = generate_api_key()
        env_content["API_KEY"] = api_key
        print(f"✓ Generated new API key: {api_key}")
    else:
        print(f"✓ Using existing API key: {env_content['API_KEY']}")
    
    # Set default values if not present
    defaults = {
        "DATABASE_URL": "postgresql://postgres:local_dev_pass_123@db/gw_repo",
        "POSTGRES_PASSWORD": "local_dev_pass_123",
        "POSTGRES_DB": "gw_repo",
        "API_BASE_URL": "http://localhost:80",
        "INSTITUTE_ID": "DKFZ",
    }
    
    for key, value in defaults.items():
        if key not in env_content:
            env_content[key] = value
    
    # Write .env file
    with open(ENV_FILE, "w") as f:
        f.write("# ===========================================\n")
        f.write("# GW-Repo Configuration - Single Source of Truth\n")
        f.write("# ===========================================\n")
        f.write("# This file is auto-generated on first run.\n")
        f.write("# Regenerate by deleting this file and running: docker compose run --rm api python migrate.py\n")
        f.write("# ===========================================\n\n")
        f.write("# API Authentication\n")
        f.write(f"API_KEY={env_content['API_KEY']}\n\n")
        f.write("# Database Configuration\n")
        f.write(f"DATABASE_URL={env_content['DATABASE_URL']}\n")
        f.write(f"POSTGRES_PASSWORD={env_content['POSTGRES_PASSWORD']}\n")
        f.write(f"POSTGRES_DB={env_content['POSTGRES_DB']}\n\n")
        f.write("# Client Configuration\n")
        f.write(f"API_BASE_URL={env_content['API_BASE_URL']}\n")
        f.write(f"INSTITUTE_ID={env_content['INSTITUTE_ID']}\n")
    
    print(f"✓ Configuration file: {ENV_FILE}")
    return env_content["API_KEY"]


def seed_default_institutes(session: Session):
    """Seed default institutes including UNKNOWN for backward compatibility."""
    from models import Institut
    
    default_institutes = [
        Institut(id="UNKNOWN", name="Unknown Institute"),
        Institut(id="LOCAL", name="Local Machine"),
        Institut(id="NONE", name="No Institute Specified"),
        Institut(id="DKFZ", name="German Cancer Research Center"),
        Institut(id="EMBL", name="European Molecular Biology Laboratory"),
    ]
    
    for inst in default_institutes:
        existing = session.get(Institut, inst.id)
        if not existing:
            print(f"  Seeding institute: {inst.id} - {inst.name}")
            session.add(inst)
        else:
            print(f"  Institute already exists: {inst.id}")
    
    session.commit()


def run_migration():
    print("=" * 60)
    print("Phase 1 Database Migration")
    print("=" * 60)
    print()
    
    # Ensure .env file exists with API key
    print("Checking configuration...")
    api_key = ensure_env_file()
    os.environ["API_KEY"] = api_key  # Set for current process
    
    print()
    print("Creating new tables...")
    
    # Import models to ensure they're registered with SQLModel metadata
    # Import from main.py to get all models including existing ones
    import main
    from models import (
        Institut,
        Hardwareinventory,
        Co2footprint,
        Workflowco2summary,
        Optimizationrule,
        Mlmodelmetadata
    )
    
    # Create all tables (SQLModel handles IF NOT EXISTS automatically)
    SQLModel.metadata.create_all(engine)
    print("  ✓ Tables created")
    
    # Seed default institutes
    print()
    print("Seeding default institutes...")
    with Session(engine) as session:
        seed_default_institutes(session)
    
    # Verify migration
    print()
    print("Verifying migration...")
    with Session(engine) as session:
        institutes = session.exec(select(Institut)).all()
        print(f"  ✓ Found {len(institutes)} institutes")
        
        # List all tables
        result = session.exec(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result.all()]
        print(f"  ✓ Total tables: {len(tables)}")
    
    print()
    print("=" * 60)
    print("Phase 1 Migration Complete!")
    print("=" * 60)
    print()
    print("New tables created:")
    print("  - institut")
    print("  - hardwareinventory")
    print("  - co2footprint")
    print("  - workflowco2summary")
    print("  - optimizationrule")
    print("  - mlmodelmetadata")
    print()
    print("Modified tables:")
    print("  - workflowexecution (added institute_id)")
    print("  - processexecution (added institute_id)")


if __name__ == "__main__":
    run_migration()
