-- Enable pgvector extension if it does not already exist
CREATE EXTENSION IF NOT EXISTS vector;

-- Table to store schema embeddings
CREATE TABLE IF NOT EXISTS schema_embeddings (
    id BIGSERIAL PRIMARY KEY,
    schema TEXT NOT NULL,
    "table" TEXT NOT NULL,
    embedding VECTOR(1024)
);

-- HNSW index on the embedding column using cosine distance
CREATE INDEX IF NOT EXISTS idx_schema_embeddings_embedding
    ON schema_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 200);

-- Function to notify about schema changes
CREATE OR REPLACE FUNCTION ddl_notify_schema_change()
RETURNS event_trigger
LANGUAGE plpgsql
AS $$
DECLARE
    cmd RECORD;
    payload JSON;
BEGIN
    FOR cmd IN SELECT * FROM pg_event_trigger_ddl_commands()
    LOOP
        IF cmd.command_tag IN ('CREATE TABLE', 'ALTER TABLE', 'DROP TABLE') THEN
            payload := json_build_object(
                'db', current_database(),
                'schema', cmd.schema_name,
                'table', cmd.object_name,
                'command', cmd.command_tag
            );
            PERFORM pg_notify('schema_changed', payload::text);
        END IF;
    END LOOP;
END;
$$;

-- Event trigger binding
DROP EVENT TRIGGER IF EXISTS trg_schema_change;
CREATE EVENT TRIGGER trg_schema_change
    ON ddl_command_end
    EXECUTE FUNCTION ddl_notify_schema_change();

-- Additional trigger to detect table drops via sql_drop events
CREATE OR REPLACE FUNCTION ddl_notify_table_drop()
RETURNS event_trigger
LANGUAGE plpgsql
AS $$
DECLARE
    obj RECORD;
    payload JSON;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_dropped_objects() LOOP
        IF obj.object_type = 'table' THEN
            payload := json_build_object(
                'db', current_database(),
                'schema', obj.schema_name,
                'table', obj.object_name,
                'command', 'DROP TABLE'
            );
            PERFORM pg_notify('schema_changed', payload::text);
        END IF;
    END LOOP;
END;
$$;

DROP EVENT TRIGGER IF EXISTS trg_table_drop;
CREATE EVENT TRIGGER trg_table_drop
    ON sql_drop
    EXECUTE FUNCTION ddl_notify_table_drop();
