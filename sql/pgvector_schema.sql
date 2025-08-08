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
    obj_name TEXT;
    sch_name TEXT;
BEGIN
    FOR cmd IN SELECT * FROM pg_event_trigger_ddl_commands()
    LOOP
        -- Skip schema_embeddings table to avoid circular triggers
        IF cmd.command_tag IN ('CREATE TABLE', 'ALTER TABLE', 'DROP TABLE') THEN
            BEGIN
                -- Safely extract object name and schema name
                obj_name := COALESCE(cmd.object_identity, cmd.objid::text, 'unknown');
                sch_name := COALESCE(cmd.schema_name, 'public');
                
                -- Skip if this is the schema_embeddings table itself
                IF obj_name LIKE '%schema_embeddings%' THEN
                    CONTINUE;
                END IF;
                
                payload := json_build_object(
                    'db', current_database(),
                    'schema', sch_name,
                    'table', obj_name,
                    'command', cmd.command_tag
                );
                PERFORM pg_notify('schema_changed', payload::text);
                
            EXCEPTION WHEN OTHERS THEN
                -- If anything fails, just skip this notification
                CONTINUE;
            END;
        END IF;
    END LOOP;
END;
$$;

-- Event trigger binding
DROP EVENT TRIGGER IF EXISTS trg_schema_change;
CREATE EVENT TRIGGER trg_schema_change
    ON ddl_command_end
    EXECUTE FUNCTION ddl_notify_schema_change();
