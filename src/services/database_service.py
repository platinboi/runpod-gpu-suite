"""
PostgreSQL Database Service for Templates
Uses Neon PostgreSQL for production-grade template storage
"""

import os
import time
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import logging
from typing import Optional, Dict, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1  # seconds
MAX_RETRY_DELAY = 10  # seconds


class DatabaseService:
    """Handles PostgreSQL database connections and operations with connection pooling"""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://neondb_owner:npg_Y3uQc9xVXgze@ep-bitter-frog-ahv64lf5-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require"
        )
        self._connection_pool = None
        self._pool_initialized = False
        # Don't initialize pool in __init__ - use lazy initialization
        # This allows the app to start even if the database is temporarily unavailable

    def _initialize_pool(self, retry: bool = True) -> bool:
        """
        Initialize the connection pool with retry logic.

        Args:
            retry: If True, retry on failure with exponential backoff

        Returns:
            True if pool was initialized successfully, False otherwise
        """
        if self._pool_initialized and self._connection_pool:
            return True

        retries = MAX_RETRIES if retry else 1
        delay = INITIAL_RETRY_DELAY

        for attempt in range(retries):
            try:
                self._connection_pool = pool.SimpleConnectionPool(
                    minconn=1,      # Start with 1 connection (faster startup)
                    maxconn=10,     # Maximum 10 concurrent connections
                    dsn=self.database_url
                )
                self._pool_initialized = True
                logger.info("✓ Database connection pool initialized (1-10 connections)")
                return True
            except Exception as e:
                logger.warning(f"Database pool initialization attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                    delay = min(delay * 2, MAX_RETRY_DELAY)  # Exponential backoff
                else:
                    logger.error(f"Failed to initialize connection pool after {retries} attempts")

        return False

    def ensure_pool(self) -> bool:
        """
        Ensure the connection pool is initialized.
        Call this before operations that require the database.

        Returns:
            True if pool is ready, False otherwise
        """
        if not self._pool_initialized:
            return self._initialize_pool(retry=True)
        return True

    @contextmanager
    def get_connection(self):
        """Context manager for database connections from pool"""
        # Lazy initialization - initialize pool on first use
        if not self._pool_initialized:
            if not self._initialize_pool(retry=True):
                raise RuntimeError("Database connection pool is not available")

        conn = None
        try:
            conn = self._connection_pool.getconn()
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn and self._connection_pool:
                self._connection_pool.putconn(conn)

    def close_pool(self):
        """Close all connections in the pool (call on shutdown)"""
        if self._connection_pool:
            self._connection_pool.closeall()
            logger.info("✓ Database connection pool closed")

    def init_templates_table(self):
        """Create templates table if it doesn't exist"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create templates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) UNIQUE NOT NULL,
                    font_path VARCHAR(500) NOT NULL,
                    font_size INTEGER NOT NULL,
                    font_weight INTEGER DEFAULT 500,
                    text_color VARCHAR(50) NOT NULL,
                    border_width INTEGER NOT NULL,
                    border_color VARCHAR(50) NOT NULL,
                    shadow_x INTEGER NOT NULL,
                    shadow_y INTEGER NOT NULL,
                    shadow_color VARCHAR(50) NOT NULL,
                    position VARCHAR(50) NOT NULL,
                    background_enabled BOOLEAN NOT NULL,
                    background_color VARCHAR(50) NOT NULL,
                    background_opacity FLOAT NOT NULL,
                    text_opacity FLOAT NOT NULL,
                    alignment VARCHAR(20) DEFAULT 'center',
                    max_text_width_percent INTEGER DEFAULT 80,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_default BOOLEAN DEFAULT FALSE
                )
            """)

            # Create indexes for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_templates_name
                ON templates(name)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_templates_created_at
                ON templates(created_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_templates_is_default
                ON templates(is_default)
            """)

            # Migration: Add max_text_width_percent column if it doesn't exist
            # This handles existing tables that were created before this column was added
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'templates'
                        AND column_name = 'max_text_width_percent'
                    ) THEN
                        ALTER TABLE templates
                        ADD COLUMN max_text_width_percent INTEGER DEFAULT 80;
                    END IF;
                END $$;
            """)

            # Migration: Add line_spacing column if it doesn't exist
            # This handles existing tables that were created before this column was added
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'templates'
                        AND column_name = 'line_spacing'
                    ) THEN
                        ALTER TABLE templates
                        ADD COLUMN line_spacing INTEGER DEFAULT -8;
                    END IF;
                END $$;
            """)

            # Create updated_at trigger
            cursor.execute("""
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ language 'plpgsql'
            """)

            cursor.execute("""
                DROP TRIGGER IF EXISTS update_templates_updated_at ON templates
            """)

            cursor.execute("""
                CREATE TRIGGER update_templates_updated_at
                BEFORE UPDATE ON templates
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """)

            logger.info("✓ Templates table initialized")

    def check_connection(self) -> bool:
        """
        Check if database connection is working.
        Returns False immediately if pool is not initialized (non-blocking).
        """
        # Quick check - if pool not initialized, don't try to initialize it
        if not self._pool_initialized or not self._connection_pool:
            return False

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            logger.warning(f"Database connection check failed: {e}")
            return False
