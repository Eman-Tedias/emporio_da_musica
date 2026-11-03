#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE ROLE agente_leitura LOGIN PASSWORD '$AGENTE_DB_PASSWORD';
    CREATE ROLE app_historico  LOGIN PASSWORD '$HISTORICO_DB_PASSWORD';

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO agente_leitura, app_historico;
    GRANT USAGE ON SCHEMA public TO agente_leitura, app_historico;

    ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
        GRANT SELECT ON TABLES TO agente_leitura;
EOSQL