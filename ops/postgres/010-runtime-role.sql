-- Local Compose role split for PostgreSQL row-level security.
--
-- The bootstrap role owns the database and runs Alembic. Application processes
-- connect as this deliberately unprivileged role. PostgreSQL superusers and roles
-- with BYPASSRLS ignore row-level policies, so sharing the bootstrap login would
-- make tenant isolation cosmetic even when every table uses FORCE ROW LEVEL SECURITY.

\getenv creatorproof_runtime_password CREATORPROOF_POSTGRES_RUNTIME_PASSWORD

SELECT 'CREATE ROLE creatorproof_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'creatorproof_app')
\gexec

ALTER ROLE creatorproof_app
    WITH LOGIN
    PASSWORD :'creatorproof_runtime_password'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOINHERIT
    NOBYPASSRLS;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE creatorproof TO creatorproof_app;
GRANT USAGE ON SCHEMA public TO creatorproof_app;

-- Alembic creates tables after this init hook. Default privileges ensure each
-- future migration remains usable by the runtime role without granting DDL or
-- ownership. The explicit grants also make this script safe to re-run manually.
ALTER DEFAULT PRIVILEGES FOR ROLE creatorproof IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO creatorproof_app;
ALTER DEFAULT PRIVILEGES FOR ROLE creatorproof IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO creatorproof_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO creatorproof_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO creatorproof_app;
