import os
import uuid
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime, Integer, Text, ForeignKey, UniqueConstraint, JSON, inspect, text, event, Engine
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from sqlalchemy.types import TypeDecorator, CHAR

# Cross-database compatible types (PostgreSQL native + SQLite fallback)
JSONB = JSON().with_variant(PG_JSONB, "postgresql")

class GUID(TypeDecorator):
    """Platform-independent GUID type. Uses PostgreSQL's UUID type, otherwise uses CHAR(36)."""
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            try:
                return uuid.UUID(value)
            except ValueError:
                return value
        return value

def UUID(*args, **kwargs):
    return GUID()

sqlite_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(sqlite_dir, exist_ok=True)
default_sqlite_url = f"sqlite:///{os.path.join(sqlite_dir, 'foodmaster_menu.db')}"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/foodmaster_menu")

from sqlalchemy.pool import NullPool, QueuePool

def _create_engine_for_url(url: str):
    if "sqlite" in url:
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool
        )
    else:
        return create_engine(
            url,
            pool_pre_ping=True,
            poolclass=QueuePool,
            pool_size=30,
            max_overflow=50,
            pool_timeout=60
        )

try:
    engine = _create_engine_for_url(DATABASE_URL)
    with engine.connect() as conn:
        pass
except Exception as e:
    DATABASE_URL = default_sqlite_url
    engine = _create_engine_for_url(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enables Write-Ahead Logging (WAL) and busy timeout for SQLite to prevent database lock errors."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.close()
        except Exception:
            pass

Base = declarative_base()

class Account(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=False) # 'shopee', 'grab', 'gofood'
    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)
    portal = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    outlets = relationship("Outlet", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("username", "platform", name="unique_account_per_platform"),
    )

    def __repr__(self):
        return f"<Account {self.platform}:{self.username}>"


class Outlet(Base):
    __tablename__ = "outlets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(String(100), unique=True, nullable=True) # Shopee/Grab/GoFood Store ID
    merchant_name = Column(String(255), nullable=False) # Portal/Merchant Selector name
    owner = Column(String(255), nullable=True) # Real Owner name from Master Google Sheet
    nama_outlet = Column(String(255), nullable=True)
    cabang = Column(String(255), nullable=True)
    nama_resto_final = Column(String(255), nullable=True)
    brand = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", back_populates="outlets")
    jobs = relationship("Job", back_populates="outlet", cascade="all, delete-orphan")
    audit_trails = relationship("AuditTrail", back_populates="outlet", cascade="all, delete-orphan")

    @property
    def platform(self):
        return self.account.platform if self.account else None

    @property
    def nama_listing(self):
        return self.nama_resto_final

    def __repr__(self):
        return f"<Outlet {self.merchant_name} ({self.store_id})>"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="SET NULL"), nullable=True)
    job_type = Column(String(50), nullable=False) # 'PULL', 'PUSH_UPDATE'
    platform = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING") # 'PENDING', 'RUNNING', 'SUCCESS', 'FAILED'
    progress_pct = Column(Integer, nullable=False, default=0)
    current_step = Column(String(255), nullable=True)
    payload = Column(JSONB, nullable=True) # GSheet/Excel upload metadata, configs
    result_metadata = Column(JSONB, nullable=True) # paths to exported file, count changes
    error_message = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=False, default="system")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    outlet = relationship("Outlet", back_populates="jobs")
    audit_trails = relationship("AuditTrail", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Job {self.job_type} - {self.status} ({self.progress_pct}%)>"


class AuditTrail(Base):
    __tablename__ = "audit_trails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(String(100), nullable=False) # applicator dish ID
    item_name = Column(String(255), nullable=False)
    change_type = Column(String(50), nullable=False) # 'CREATE_ITEM', 'UPDATE_PRICE', etc.
    field_changed = Column(String(100), nullable=False) # 'price', 'availability', etc.
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=False)
    status = Column(String(50), nullable=False) # 'SUCCESS', 'FAILED'
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="audit_trails")
    outlet = relationship("Outlet", back_populates="audit_trails")

    def __repr__(self):
        return f"<AuditTrail {self.change_type} {self.item_name} -> {self.status}>"


def init_db():
    """Initializes the database, creating all tables if they do not exist, and auto-migrating missing columns."""
    global engine, SessionLocal, DATABASE_URL
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        DATABASE_URL = default_sqlite_url
        engine = _create_engine_for_url(DATABASE_URL)
        SessionLocal.configure(bind=engine)
        try:
            Base.metadata.create_all(bind=engine)
        except Exception:
            pass

    # Auto-migrate missing columns for existing SQLite / Postgres tables
    try:
        inspector = inspect(engine)
        if "outlets" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("outlets")]
            with engine.begin() as conn:
                if "owner" not in columns:
                    conn.execute(text("ALTER TABLE outlets ADD COLUMN owner VARCHAR(255)"))
                if "nama_outlet" not in columns:
                    conn.execute(text("ALTER TABLE outlets ADD COLUMN nama_outlet VARCHAR(255)"))
                if "cabang" not in columns:
                    conn.execute(text("ALTER TABLE outlets ADD COLUMN cabang VARCHAR(255)"))
                if "nama_resto_final" not in columns:
                    conn.execute(text("ALTER TABLE outlets ADD COLUMN nama_resto_final VARCHAR(255)"))
                if "brand" not in columns:
                    conn.execute(text("ALTER TABLE outlets ADD COLUMN brand VARCHAR(255)"))
                # Create indexes if they do not exist to optimize joins and filtering
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_outlets_account_id ON outlets(account_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_outlets_store_id ON outlets(store_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_outlet_id ON jobs(outlet_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_status_type ON jobs(job_type, status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_trails_outlet_id ON audit_trails(outlet_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_trails_item_id ON audit_trails(item_id)"))
    except Exception as migrate_err:
        pass


def get_db():
    """Dependency helper to get database session context."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Ensure missing columns are auto-migrated on module load
try:
    init_db()
except Exception:
    pass
