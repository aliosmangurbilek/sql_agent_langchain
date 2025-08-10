-- Enable pgvector extension if it does not already exist
CREATE EXTENSION IF NOT EXISTS vector;

-- Table to store schema embeddings (tenant-aware by database)
CREATE TABLE IF NOT EXISTS schema_embeddings (
    id BIGSERIAL PRIMARY KEY,
    db_name TEXT NOT NULL,
    schema TEXT NOT NULL,
    "table" TEXT NOT NULL,
    embedding VECTOR(1024)
);

-- Unique constraint per database+table
CREATE UNIQUE INDEX IF NOT EXISTS ux_schema_embeddings_db_table
    ON schema_embeddings (db_name, schema, "table");

-- HNSW index on the embedding column using cosine distance
CREATE INDEX IF NOT EXISTS idx_schema_embeddings_embedding
    ON schema_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 200);

-- Event trigger function: notify on CREATE/ALTER/DROP TABLE (skip our own table)
CREATE OR REPLACE FUNCTION ddl_notify_schema_change()
RETURNS event_trigger
LANGUAGE plpgsql
AS $$
DECLARE
    cmd RECORD;
    payload JSON;
    obj_name TEXT;
    sch_name TEXT;
    tbl_name TEXT;
BEGIN
    FOR cmd IN SELECT * FROM pg_event_trigger_ddl_commands()
    LOOP
        IF cmd.command_tag IN ('CREATE TABLE', 'ALTER TABLE', 'DROP TABLE') THEN
            BEGIN
                obj_name := COALESCE(cmd.object_identity, cmd.objid::text, 'unknown');
                sch_name := COALESCE(cmd.schema_name, 'public');

                -- Extract pure table name if object_identity is "schema.table"
                IF position('.' in obj_name) > 0 THEN
                    tbl_name := split_part(obj_name, '.', 2);
                ELSE
                    tbl_name := obj_name;
                END IF;

                -- Skip notifications for our embeddings table itself
                IF tbl_name ILIKE 'schema_embeddings' THEN
                    CONTINUE;
                END IF;

                payload := json_build_object(
                    'db', current_database(),
                    'schema', sch_name,
                    'table', tbl_name,
                    'command', cmd.command_tag
                );

                PERFORM pg_notify('schema_changed', payload::text);

            EXCEPTION WHEN OTHERS THEN
                CONTINUE;
            END;
        END IF;
    END LOOP;
END;
$$;

-- Bind trigger
DROP EVENT TRIGGER IF EXISTS trg_schema_change;
CREATE EVENT TRIGGER trg_schema_change
    ON ddl_command_end
    EXECUTE FUNCTION ddl_notify_schema_change();