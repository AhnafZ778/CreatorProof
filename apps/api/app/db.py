from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


_STARTUP_ADVISORY_LOCK_ID = 74_148_833_103_174

# This mirrors the tenant policies installed by revisions 0003 and 0004. Keeping
# the assertion at the runtime connection boundary prevents a deployment from
# reporting healthy after accidentally connecting with the migration owner or to
# a database whose RLS migration was skipped.
_RLS_REQUIRED_TABLES = frozenset(
    {
        "works",
        "scans",
        "principals",
        "api_credentials",
        "deletion_receipts",
        "catalogs",
        "catalog_versions",
        "asset_versions",
        "corpus_snapshots",
        "scan_input_bindings",
        "evidence_statements",
        "parties",
        "creator_profiles",
        "claims",
        "licenses",
        "rights_events",
        "policy_versions",
        "review_cases",
        "review_events",
        "webhook_endpoints",
        "webhook_deliveries",
        "usage_records",
        "integrity_events",
        "blockchain_anchor_jobs",
        "network_members",
        "counterparty_attestations",
    }
)


def _runtime_role_safety_problems(role: dict, table_states: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    role_name = str(role.get("role_name") or "<unknown>")
    if role.get("rolsuper"):
        problems.append(f"runtime role {role_name!r} is a PostgreSQL superuser")
    if role.get("rolbypassrls"):
        problems.append(f"runtime role {role_name!r} has BYPASSRLS")

    missing = sorted(_RLS_REQUIRED_TABLES - table_states.keys())
    if missing:
        problems.append("required migrated tables are missing: " + ", ".join(missing))
    unsafe_rls = sorted(
        table
        for table in _RLS_REQUIRED_TABLES & table_states.keys()
        if not table_states[table].get("relrowsecurity")
        or not table_states[table].get("relforcerowsecurity")
    )
    if unsafe_rls:
        problems.append("RLS is not enabled and forced on: " + ", ".join(unsafe_rls))
    owned = sorted(
        table
        for table in _RLS_REQUIRED_TABLES & table_states.keys()
        if table_states[table].get("owned_by_current")
    )
    if owned:
        problems.append(
            "runtime role owns migration-managed tables (use a separate owner): " + ", ".join(owned)
        )
    return problems


@dataclass(slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()

    def system_session(self) -> Session:
        """Open a session reserved for trusted cross-tenant background work.

        Request handlers must use ``session_factory`` and bind a tenant after
        authentication. Global dispatchers and recovery jobs cannot know a tenant
        before they claim work, so they receive this separate, explicit factory.
        The RLS override is transaction-local and is automatically restored after
        each commit by ``app.services.tenancy``.
        """
        from app.services.tenancy import bind_system_context

        db = self.session_factory()
        try:
            bind_system_context(db)
        except Exception:
            db.close()
            raise
        return db

    @contextmanager
    def startup_lock(self) -> Iterator[None]:
        """Serialize cross-process seed initialization on PostgreSQL.

        A dedicated connection owns the session-level advisory lock while the
        seeding session performs several commits. This avoids returning a locked
        physical connection to the pool between commits and covers API/worker
        cold starts without coupling policy code to deployment topology.
        """
        if self.engine.dialect.name != "postgresql":
            yield
            return
        with self.engine.connect() as guard:
            guard.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": _STARTUP_ADVISORY_LOCK_ID},
            )
            guard.commit()
            try:
                yield
            finally:
                if guard.in_transaction():
                    guard.rollback()
                guard.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": _STARTUP_ADVISORY_LOCK_ID},
                )
                guard.commit()

    def assert_runtime_role_safety(self, *, require_rls: bool) -> None:
        """Fail startup when PostgreSQL can bypass the intended tenant boundary."""
        if self.engine.dialect.name != "postgresql" or not require_rls:
            return
        with self.engine.connect() as connection:
            role = (
                connection.execute(
                    text(
                        "SELECT current_user AS role_name, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
                .mappings()
                .one()
            )
            rows = connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
                    "AS owned_by_current "
                    "FROM pg_class AS c "
                    "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')"
                )
            ).mappings()
            table_states = {str(row["relname"]): dict(row) for row in rows}
        problems = _runtime_role_safety_problems(dict(role), table_states)
        if problems:
            raise RuntimeError("Unsafe PostgreSQL runtime role/schema: " + "; ".join(problems))


def _configure_sqlite_connection(dbapi_connection, _connection_record):
    """Enable WAL mode and a generous busy timeout for every new SQLite connection.

    WAL allows concurrent reads while a write is in progress.  The busy timeout
    prevents immediate 'database is locked' errors when the background scan thread
    and the API request thread write at nearly the same time.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def build_database(settings: Settings) -> Database:
    is_sqlite = settings.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    if is_sqlite:
        event.listen(engine, "connect", _configure_sqlite_connection)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return Database(engine=engine, session_factory=factory)
