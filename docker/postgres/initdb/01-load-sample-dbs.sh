#!/bin/bash
set -Eeuo pipefail

SAMPLE_DB_DIR="${SAMPLE_DB_DIR:-/sample-dbs}"
SAMPLE_DATABASES_RAW="${SAMPLE_DATABASES:-pagila,chinook,titanic,netflix,periodic_table,happiness_index}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

restore_sample_db() {
  local db_name="$1"
  local dump_path="$2"

  echo "Loading sample database '${db_name}' from ${dump_path##*/}"

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
SELECT 'CREATE DATABASE "$db_name"'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$db_name')\gexec
SQL

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_name" -c 'CREATE EXTENSION IF NOT EXISTS vector;'

  case "$dump_path" in
    *.sql)
      psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_name" -f "$dump_path"
      ;;
    *.sql.gz)
      gunzip -c "$dump_path" | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_name"
      ;;
    *)
      echo "Unsupported sample dump: $dump_path" >&2
      return 1
      ;;
  esac
}

IFS=',' read -r -a sample_db_list <<< "$SAMPLE_DATABASES_RAW"

for raw_name in "${sample_db_list[@]}"; do
  db_name="$(trim "$raw_name")"
  if [ -z "$db_name" ]; then
    continue
  fi

  dump_path=""
  if [ -f "$SAMPLE_DB_DIR/${db_name}.sql" ]; then
    dump_path="$SAMPLE_DB_DIR/${db_name}.sql"
  elif [ -f "$SAMPLE_DB_DIR/${db_name}.sql.gz" ]; then
    dump_path="$SAMPLE_DB_DIR/${db_name}.sql.gz"
  fi

  if [ -z "$dump_path" ]; then
    echo "Skipping sample database '${db_name}': dump file not found in ${SAMPLE_DB_DIR}" >&2
    continue
  fi

  restore_sample_db "$db_name" "$dump_path"
done
