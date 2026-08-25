#!/usr/bin/env python3
"""
Migration script to auto-tag existing process executions with data size categories.

Tags based on disk_usage_mb percentiles:
- small: 0-33rd percentile
- medium: 33rd-67th percentile
- large: 67th-100th percentile

Also updates workflow executions with the most common tag from their processes.
"""

import pandas as pd
from sqlmodel import SQLModel, create_engine, Session, select, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:local_dev_pass_123@db/gw_repo")
engine = create_engine(DATABASE_URL, echo=False)


def migrate_process_size_tags():
    """Add data_size_tag to ProcessExecution based on disk_usage_mb percentiles."""
    
    print("📊 Analyzing existing process execution data...")
    
    # Load all process executions
    query = """
    SELECT id, workflow_execution_id, disk_usage_mb
    FROM processexecution
    WHERE disk_usage_mb IS NOT NULL
    """
    
    df = pd.read_sql(query, engine)
    
    if df.empty:
        print("❌ No process executions with disk_usage_mb found!")
        return
    
    print(f"✅ Found {len(df)} process executions with disk usage data")
    print(f"   Size range: {df['disk_usage_mb'].min():.2f} MB - {df['disk_usage_mb'].max():.2f} MB")
    print(f"   Median: {df['disk_usage_mb'].median():.2f} MB")
    
    # Calculate percentiles
    p33 = df['disk_usage_mb'].quantile(0.33)
    p67 = df['disk_usage_mb'].quantile(0.67)
    
    print(f"\n📏 Size thresholds (based on percentiles):")
    print(f"   Small:  0 - {p33:.2f} MB (0-33rd percentile)")
    print(f"   Medium: {p33:.2f} - {p67:.2f} MB (33rd-67th percentile)")
    print(f"   Large:  {p67:.2f}+ MB (67th-100th percentile)")
    
    # Assign tags
    def assign_tag(disk_mb):
        if disk_mb <= p33:
            return 'small'
        elif disk_mb <= p67:
            return 'medium'
        else:
            return 'large'
    
    df['data_size_tag'] = df['disk_usage_mb'].apply(assign_tag)
    
    # Show distribution
    print(f"\n📊 Tag distribution:")
    for tag in ['small', 'medium', 'large']:
        count = (df['data_size_tag'] == tag).sum()
        pct = count / len(df) * 100
        print(f"   {tag}: {count} ({pct:.1f}%)")
    
    # Update database
    print(f"\n🔄 Updating database...")
    with Session(engine) as session:
        for _, row in df.iterrows():
            # Add column if it doesn't exist (first run)
            try:
                from main import ProcessExecution
                process = session.get(ProcessExecution, row['id'])
                if process:
                    process.data_size_tag = row['data_size_tag']
            except Exception as e:
                # Column might not exist yet, skip
                pass
        
        session.commit()
    
    print(f"✅ Migration complete!")
    
    return {
        'p33': p33,
        'p67': p67,
        'counts': df['data_size_tag'].value_counts().to_dict()
    }


def migrate_workflow_size_tags():
    """Update workflow executions with most common size tag from their processes."""
    
    print("\n📊 Migrating workflow size tags...")
    
    query = """
    SELECT 
        w.id as workflow_id,
        COUNT(DISTINCT p.data_size_tag) as tag_count,
        MODE() WITHIN GROUP (ORDER BY p.data_size_tag) as most_common_tag
    FROM workflowexecution w
    LEFT JOIN processexecution p ON w.id = p.workflow_execution_id
    WHERE p.data_size_tag IS NOT NULL
    GROUP BY w.id
    """
    
    try:
        df = pd.read_sql(query, engine)
        
        if df.empty:
            print("⚠️  No workflows with tagged processes found")
            return
        
        print(f"✅ Found {len(df)} workflows with tagged processes")
        
        with Session(engine) as session:
            from main import WorkflowExecution
            
            for _, row in df.iterrows():
                workflow = session.get(WorkflowExecution, row['workflow_id'])
                if workflow and row['most_common_tag']:
                    workflow.data_size_tag = row['most_common_tag']
            
            session.commit()
        
        print(f"✅ Workflow migration complete!")
        
    except Exception as e:
        print(f"⚠️  Workflow migration skipped (column may not exist yet): {e}")


def add_columns_if_missing():
    """Add data_size_tag columns if they don't exist."""
    
    print("🔧 Checking database schema...")
    
    with engine.connect() as conn:
        # Check if column exists in processexecution
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'processexecution' 
            AND column_name = 'data_size_tag'
        """))
        
        if not result.fetchone():
            print("   Adding data_size_tag to processexecution...")
            conn.execute(text("""
                ALTER TABLE processexecution 
                ADD COLUMN data_size_tag VARCHAR(20)
            """))
            conn.commit()
            print("   ✅ Column added")
        else:
            print("   ✅ data_size_tag already exists in processexecution")
        
        # Check workflowexecution
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'workflowexecution' 
            AND column_name = 'data_size_tag'
        """))
        
        if not result.fetchone():
            print("   Adding data_size_tag to workflowexecution...")
            conn.execute(text("""
                ALTER TABLE workflowexecution 
                ADD COLUMN data_size_tag VARCHAR(20)
            """))
            conn.commit()
            print("   ✅ Column added")
        else:
            print("   ✅ data_size_tag already exists in workflowexecution")


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Starting Data Size Tag Migration")
    print("=" * 60)
    
    # Step 1: Add columns if missing
    add_columns_if_missing()
    
    # Step 2: Tag process executions
    migrate_process_size_tags()
    
    # Step 3: Tag workflow executions
    migrate_workflow_size_tags()
    
    print("\n" + "=" * 60)
    print("✅ Migration Complete!")
    print("=" * 60)
