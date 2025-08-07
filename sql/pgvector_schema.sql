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
    table_name TEXT;
    schema_name TEXT;
    full_object_name TEXT;
BEGIN
    -- Log the trigger activation
    RAISE NOTICE 'DDL Event Trigger activated';
    
    FOR cmd IN SELECT * FROM pg_event_trigger_ddl_commands()
    LOOP
        RAISE NOTICE 'Processing command: tag=%, type=%, identity=%', cmd.command_tag, cmd.object_type, cmd.object_identity;
        
        IF cmd.command_tag IN ('CREATE TABLE', 'ALTER TABLE', 'DROP TABLE') THEN
            -- Extract schema and table name more safely
            IF cmd.object_type = 'table' THEN
                -- Get full object identity
                full_object_name := cmd.object_identity;
                
                -- Parse schema.table from object_identity
                IF position('.' in full_object_name) > 0 THEN
                    schema_name := split_part(full_object_name, '.', 1);
                    table_name := split_part(full_object_name, '.', 2);
                ELSE
                    schema_name := 'public';
                    table_name := full_object_name;
                END IF;
                
                -- Clean up quoted identifiers
                schema_name := trim(both '"' from schema_name);
                table_name := trim(both '"' from table_name);
                
                -- Build notification payload
                payload := json_build_object(
                    'db', current_database(),
                    'schema', schema_name,
                    'table', table_name,
                    'command', cmd.command_tag,
                    'object_type', cmd.object_type,
                    'object_identity', cmd.object_identity
                );
                
                -- Send notification
                PERFORM pg_notify('schema_changed', payload::text);
                
                -- Log for debugging
                RAISE NOTICE 'DDL notification sent: %', payload::text;
            END IF;
        END IF;
    END LOOP;
EXCEPTION
    WHEN OTHERS THEN
        -- Log error but don't fail the DDL command
        RAISE WARNING 'Error in ddl_notify_schema_change: % %', SQLSTATE, SQLERRM;
END;
$$;

-- Event trigger binding
DROP EVENT TRIGGER IF EXISTS trg_schema_change;
CREATE EVENT TRIGGER trg_schema_change
    ON ddl_command_end
    EXECUTE FUNCTION ddl_notify_schema_change();

-- Additional trigger for DROP events (sql_drop)
CREATE OR REPLACE FUNCTION ddl_notify_drop()
RETURNS event_trigger
LANGUAGE plpgsql
AS $$
DECLARE
    obj RECORD;
    payload JSON;
    table_name TEXT;
    schema_name TEXT;
BEGIN
    RAISE NOTICE 'DROP Event Trigger activated';
    
    FOR obj IN SELECT * FROM pg_event_trigger_dropped_objects()
    LOOP
        RAISE NOTICE 'Processing drop: type=%, identity=%', obj.object_type, obj.object_identity;
        
        IF obj.object_type = 'table' THEN
            -- Parse schema.table from object_identity
            IF position('.' in obj.object_identity) > 0 THEN
                schema_name := split_part(obj.object_identity, '.', 1);
                table_name := split_part(obj.object_identity, '.', 2);
            ELSE
                schema_name := 'public';
                table_name := obj.object_identity;
            END IF;
            
            -- Clean up quoted identifiers
            schema_name := trim(both '"' from schema_name);
            table_name := trim(both '"' from table_name);
            
            -- Build notification payload
            payload := json_build_object(
                'db', current_database(),
                'schema', schema_name,
                'table', table_name,
                'command', 'DROP TABLE',
                'object_type', obj.object_type,
                'object_identity', obj.object_identity
            );
            
            -- Send notification
            PERFORM pg_notify('schema_changed', payload::text);
            
            -- Log for debugging
            RAISE NOTICE 'DROP notification sent: %', payload::text;
        END IF;
    END LOOP;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Error in ddl_notify_drop: % %', SQLSTATE, SQLERRM;
END;
$$;

-- Drop trigger for better DROP TABLE detection
DROP EVENT TRIGGER IF EXISTS trg_schema_drop;
CREATE EVENT TRIGGER trg_schema_drop
    ON sql_drop
    EXECUTE FUNCTION ddl_notify_drop();
