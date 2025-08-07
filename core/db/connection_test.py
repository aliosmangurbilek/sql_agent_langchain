"""
Database connection testing utilities
"""

import logging
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def test_database_connection(db_uri: str) -> dict:
    """
    Test database connection without importing heavy ML libraries.
    Returns status and message.
    """
    try:
        # Create engine with minimal overhead
        engine = sa.create_engine(
            db_uri, pool_pre_ping=True, pool_recycle=300, echo=False
        )

        # Test connection
        with engine.connect() as conn:
            # Simple query to test connection
            result = conn.execute(sa.text("SELECT 1 as test"))
            row = result.fetchone()

            if row and row[0] == 1:
                return {
                    "status": "success",
                    "message": "Database connection successful",
                    "connected": True,
                }
            else:
                return {
                    "status": "error",
                    "message": "Connection test failed",
                    "connected": False,
                }

    except SQLAlchemyError as e:
        logger.error(f"Database connection error: {e}")
        return {
            "status": "error",
            "message": f"Database error: {str(e)}",
            "connected": False,
        }
    except Exception as e:
        logger.error(f"Unexpected error testing connection: {e}")
        return {
            "status": "error",
            "message": f"Connection error: {str(e)}",
            "connected": False,
        }
    finally:
        try:
            engine.dispose()
        except:
            pass
