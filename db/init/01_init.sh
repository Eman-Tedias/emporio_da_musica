#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE ROLE agent_reader LOGIN PASSWORD '$AGENT_DB_PASSWORD';
    CREATE ROLE history_writer  LOGIN PASSWORD '$HISTORY_DB_PASSWORD';

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO agent_reader, history_writer;
    GRANT USAGE ON SCHEMA public TO agent_reader, history_writer;

    ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
        GRANT SELECT ON TABLES TO agent_reader;
EOSQL