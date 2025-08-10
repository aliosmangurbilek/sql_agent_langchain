"""
Database Manager - Dynamic database connection and embedding management
"""
from __future__ import annotations

import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from .connection_test import test_database_connection
from .embedder import DBEmbedder
from .introspector import get_metadata

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages multiple database connections and their embeddings dynamically."""
    
    def __init__(self):
        self._engine_cache: Dict[str, sa.Engine] = {}
        self._embedder_cache: Dict[str, DBEmbedder] = {}
        self._table_cache: Dict[str, List[Tuple[str, str]]] = {}  # db_uri -> [(schema, table), ...]
        
    def _get_db_name_from_uri(self, db_uri: str) -> str:
        """Extract database name from URI."""
        try:
            parsed = urlparse(db_uri)
            db_name = parsed.path.lstrip('/')
            return db_name if db_name else 'default'
        except Exception:
            return 'default'
    
    def test_connection(self, db_uri: str) -> Dict[str, any]:
        """Test database connection and return status."""
        try:
            result = test_database_connection(db_uri)
            if result.get('connected', False):
                # Cache basic info about available tables
                self._cache_table_info(db_uri)
            return result
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return {
                'status': 'error',
                'connected': False,
                'message': str(e)
            }
    
    def _cache_table_info(self, db_uri: str) -> None:
        """Cache basic table information for quick fallback."""
        try:
            engine = self._get_engine(db_uri)
            with engine.connect() as conn:
                tables = conn.execute(sa.text("""
                    SELECT table_schema, table_name 
                    FROM information_schema.tables 
                    WHERE table_type = 'BASE TABLE'
                    AND table_schema NOT IN ('information_schema', 'pg_catalog')
                    ORDER BY table_schema, table_name
                """)).fetchall()
                
                self._table_cache[db_uri] = [(row[0], row[1]) for row in tables]
                logger.info(f"Cached {len(tables)} tables for {db_uri}")
                
        except Exception as e:
            logger.warning(f"Could not cache table info for {db_uri}: {e}")
            self._table_cache[db_uri] = []
    
    def _get_engine(self, db_uri: str) -> sa.Engine:
        """Get or create SQLAlchemy engine for database."""
        if db_uri not in self._engine_cache:
            self._engine_cache[db_uri] = sa.create_engine(
                db_uri, 
                pool_pre_ping=True,
                pool_recycle=3600
            )
        return self._engine_cache[db_uri]
    
    def get_embedder(self, db_uri: str) -> DBEmbedder:
        """Get or create embedder for database."""
        if db_uri not in self._embedder_cache:
            engine = self._get_engine(db_uri)
            db_name = self._get_db_name_from_uri(db_uri)
            self._embedder_cache[db_uri] = DBEmbedder(engine=engine, db_name=db_name)
        
        return self._embedder_cache[db_uri]
    
    def ensure_embeddings(self, db_uri: str, force_rebuild: bool = False) -> Dict[str, any]:
        """Ensure embeddings exist for the database, create if needed."""
        try:
            embedder = self.get_embedder(db_uri)
            
            # Check if embeddings already exist
            db_name = self._get_db_name_from_uri(db_uri)
            
            # Quick check for existing embeddings
            engine = self._get_engine(db_uri)
            
            # Check if pgvector table exists and has embeddings
            # Check if we have embeddings for this database
            has_embeddings = False
            try:
                with engine.connect() as conn:
                    # Check if schema_embeddings table exists
                    table_exists = conn.execute(sa.text("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'schema_embeddings'
                        )
                    """)).scalar()
                    
                    if table_exists:
                        # Check if db_name column exists
                        db_name_column_exists = conn.execute(sa.text("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.columns 
                                WHERE table_name = 'schema_embeddings' 
                                AND column_name = 'db_name'
                            )
                        """)).scalar()
                        
                        if db_name_column_exists:
                            # Check if we have embeddings for this database
                            count = conn.execute(sa.text("""
                                SELECT COUNT(*) FROM schema_embeddings 
                                WHERE db_name = :db_name
                            """), {"db_name": db_name}).scalar()
                            has_embeddings = count > 0
                        else:
                            # Old schema without db_name column - check if any embeddings exist
                            count = conn.execute(sa.text("""
                                SELECT COUNT(*) FROM schema_embeddings
                            """)).scalar()
                            has_embeddings = count > 0
                            # If embeddings exist but no db_name column, we should rebuild
                            if has_embeddings:
                                logger.warning("Found old schema_embeddings table without db_name column")
                                has_embeddings = False  # Force rebuild with new schema
                        
            except Exception as e:
                logger.warning(f"Could not check existing embeddings: {e}")
                has_embeddings = False
            
            if not has_embeddings or force_rebuild:
                logger.info(f"Building embeddings for database: {db_name}")
                embedder.ensure_store(force=force_rebuild)
                return {
                    'status': 'success',
                    'message': f'Embeddings created for {db_name}',
                    'action': 'created'
                }
            else:
                logger.info(f"Embeddings already exist for database: {db_name}")
                return {
                    'status': 'success', 
                    'message': f'Embeddings already exist for {db_name}',
                    'action': 'exists'
                }
                
        except Exception as e:
            logger.error(f"Failed to ensure embeddings for {db_uri}: {e}")
            return {
                'status': 'error',
                'message': str(e),
                'action': 'failed'
            }
    
    def get_tables_fallback(self, db_uri: str) -> List[str]:
        """Get table list as fallback when embeddings are not available."""
        if db_uri in self._table_cache:
            return [f"{schema}.{table}" for schema, table in self._table_cache[db_uri]]
        
        # Try to get tables directly from database
        try:
            engine = self._get_engine(db_uri)
            with engine.connect() as conn:
                tables = conn.execute(sa.text("""
                    SELECT table_schema, table_name 
                    FROM information_schema.tables 
                    WHERE table_type = 'BASE TABLE'
                    AND table_schema NOT IN ('information_schema', 'pg_catalog')
                    ORDER BY table_schema, table_name
                    LIMIT 20
                """)).fetchall()
                
                return [f"{row[0]}.{row[1]}" for row in tables]
                
        except Exception as e:
            logger.error(f"Could not get fallback tables for {db_uri}: {e}")
            return []
    
    def search_tables(self, db_uri: str, query: str, k: int = 5) -> List[Dict[str, any]]:
        """Search for relevant tables using embeddings or fallback to all tables."""
        try:
            embedder = self.get_embedder(db_uri)
            results = embedder.similarity_search(query, k=k)
            
            if results:
                return results
            else:
                # Fallback to basic table list
                logger.warning(f"No embedding results for query '{query}', using fallback")
                tables = self.get_tables_fallback(db_uri)
                return [
                    {
                        'table': table,
                        'score': 0.5,  # Default score
                        'text': f'Table {table}'
                    }
                    for table in tables[:k]
                ]
                
        except Exception as e:
            logger.error(f"Table search failed for {db_uri}: {e}")
            # Final fallback
            tables = self.get_tables_fallback(db_uri)
            return [
                {
                    'table': table,
                    'score': 0.3,  # Lower default score
                    'text': f'Table {table} (fallback)'
                }
                for table in tables[:k]
            ]
    
    def get_database_info(self, db_uri: str) -> Dict[str, any]:
        """Get comprehensive information about a database."""
        try:
            # Test connection
            connection_status = self.test_connection(db_uri)
            if not connection_status.get('connected', False):
                return connection_status
            
            # Get table count
            tables = self.get_tables_fallback(db_uri)
            
            # Check embedding status
            db_name = self._get_db_name_from_uri(db_uri)
            embedding_status = self.ensure_embeddings(db_uri, force_rebuild=False)
            
            return {
                'status': 'success',
                'connected': True,
                'db_name': db_name,
                'table_count': len(tables),
                'tables': tables[:10],  # First 10 tables
                'embedding_status': embedding_status.get('action', 'unknown'),
                'message': f"Database {db_name} ready with {len(tables)} tables"
            }
            
        except Exception as e:
            logger.error(f"Failed to get database info for {db_uri}: {e}")
            return {
                'status': 'error',
                'connected': False,
                'message': str(e)
            }
    
    def cleanup_cache(self):
        """Clean up cached connections and embedders."""
        for engine in self._engine_cache.values():
            try:
                engine.dispose()
            except Exception:
                pass
        
        self._engine_cache.clear()
        self._embedder_cache.clear()
        self._table_cache.clear()


# Global instance
database_manager = DatabaseManager()
