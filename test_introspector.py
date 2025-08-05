# Simple introspector test
import sqlalchemy as sa

def test_simple_metadata(db_uri):
    """Test with a simpler metadata query"""
    engine = sa.create_engine(db_uri)
    
    simple_sql = sa.text("""
        SELECT
            schemaname as schema,
            tablename as table,
            NULL as column,
            'table' as data_type,
            FALSE as is_nullable,
            FALSE as is_primary_key,
            '' as fk_refs,
            0 as row_estimate,
            0 as table_size_mb,
            NULL as table_comment,
            NULL as column_comment
        FROM pg_tables 
        WHERE schemaname NOT IN ('pg_catalog','information_schema')
        ORDER BY schemaname, tablename;
    """)
    
    with engine.connect() as conn:
        rows = conn.execute(simple_sql).mappings().all()
        return [dict(row) for row in rows]

if __name__ == "__main__":
    db_uri = "postgresql://postgres:2336@localhost:5432/happiness_index"
    result = test_simple_metadata(db_uri)
    print(f"Found {len(result)} tables")
    for row in result[:5]:
        print(row)
