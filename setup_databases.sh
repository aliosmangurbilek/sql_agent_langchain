#!/bin/bash

# Setup pgvector schema in all databases
# This script will create the necessary pgvector extension and schema_embeddings table
# in each of your databases

DATABASES=("happiness_index" "netflix" "lego" "pagila" "employees")
PG_USER="postgres"
PG_PASSWORD="2336"
PG_HOST="localhost"
PG_PORT="5432"

echo "🚀 Setting up pgvector schema in all databases..."

for db in "${DATABASES[@]}"; do
    echo "📊 Setting up database: $db"
    
    # Set password for psql
    export PGPASSWORD=$PG_PASSWORD
    
    # Run the schema setup
    psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $db -f sql/pgvector_schema.sql
    
    if [ $? -eq 0 ]; then
        echo "✅ Successfully set up pgvector schema in $db"
    else
        echo "❌ Failed to set up pgvector schema in $db"
    fi
done

echo "🎉 Database setup complete!"
echo "📝 Available databases:"
for db in "${DATABASES[@]}"; do
    echo "   - postgresql://postgres:2336@localhost:5432/$db"
done
