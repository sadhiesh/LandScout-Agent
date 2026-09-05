"""Database migration runner for LandScout.

File-driven migration system. Applies memory/schema/*.sql in order,
tracking applied versions in schema_migrations ledger.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Schema files directory
SCHEMA_DIR = Path(__file__).parent / "schema"


def _ensure_migrations_table(cur) -> None:
    """Create schema_migrations ledger if it doesn't exist."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def _get_applied_versions(cur) -> set[str]:
    """Get set of already-applied migration versions."""
    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {row["version"] for row in cur.fetchall()}


def _get_pending_migrations(applied: set[str]) -> list[tuple[str, Path]]:
    """Get list of (version, filepath) for pending migrations in order."""
    if not SCHEMA_DIR.exists():
        logger.warning(f"Schema directory not found: {SCHEMA_DIR}")
        return []
    
    migrations = []
    for sql_file in sorted(SCHEMA_DIR.glob("*.sql")):
        version = sql_file.stem  # e.g., "001_sessions"
        if version not in applied:
            migrations.append((version, sql_file))
    
    return migrations


def migrate(dsn: str) -> None:
    """Apply pending database migrations from memory/schema/*.
    
    Each .sql file is applied in a transaction. Already-applied files
    (tracked in schema_migrations) are skipped.
    
    Args:
        dsn: PostgreSQL connection string
        
    Raises:
        RuntimeError: If any migration fails
    """
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # Ensure the migrations ledger exists
                _ensure_migrations_table(cur)
                conn.commit()
                
                # Get pending migrations
                applied = _get_applied_versions(cur)
                pending = _get_pending_migrations(applied)
                
                if not pending:
                    logger.info("No pending migrations")
                    return
                
                logger.info(f"Found {len(pending)} pending migration(s)")
                
                # Apply each migration in order
                for version, filepath in pending:
                    logger.info(f"Applying {version}: {filepath.name}")
                    
                    # Read and execute the migration SQL
                    sql = filepath.read_text()
                    cur.execute(sql)
                    
                    # Record it in the ledger
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,)
                    )
                    conn.commit()
                    
                    logger.info(f"Applied {version}")
                
                logger.info("Database migrations completed successfully")
                
    except psycopg.Error as e:
        raise RuntimeError(f"Migration failed: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Migration runner error: {e}") from e


def verify(dsn: str) -> bool:
    """Verify that all schema files have been applied.
    
    Args:
        dsn: PostgreSQL connection string
        
    Returns:
        True if all migrations applied, False otherwise
    """
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # Check migrations table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'schema_migrations'
                    )
                """)
                if not cur.fetchone()["exists"]:
                    logger.error("schema_migrations table not found")
                    return False
                
                # Get applied and expected versions
                applied = _get_applied_versions(cur)
                pending = _get_pending_migrations(applied)
                
                if pending:
                    logger.error(f"Unapplied migrations: {[v for v, _ in pending]}")
                    return False
                
                logger.info(f"Schema verification passed ({len(applied)} migrations applied)")
                return True
                
    except psycopg.Error as e:
        logger.error(f"Schema verification failed: {e}")
        return False


if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path
    
    # Add repo root to path so we can import agents
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root))
    
    from agents.common.config import POSTGRES_DSN
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    if "--verify" in sys.argv:
        success = verify(POSTGRES_DSN)
        sys.exit(0 if success else 1)
    else:
        migrate(POSTGRES_DSN)
