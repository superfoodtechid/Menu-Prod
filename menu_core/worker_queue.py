"""Database-backed worker leasing for hybrid VM1/Raspberry Pi jobs."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, or_

from .database import Job

SUPPORTED_WORKER_TARGETS = {"vm1", "pi", "auto"}
PI_PULL_PLATFORMS = {"shopee", "grab"}


def validate_worker_target(value: Optional[str]) -> str:
    target = (value or "vm1").strip().lower()
    if target not in SUPPORTED_WORKER_TARGETS:
        raise ValueError("worker_target harus vm1, pi, atau auto")
    return target


def claim_next_pull_job(
    db,
    worker_id: str,
    lease_seconds: int = 7200,
    auto_after_seconds: int = 0,
):
    """Atomically claim one PULL job eligible for this worker.

    PostgreSQL uses SKIP LOCKED so VM1 and Pi cannot claim the same job. SQLite
    keeps the same transaction shape for local tests, where SKIP LOCKED is
    ignored by the dialect.
    """
    worker_id = (worker_id or "").strip().lower()
    if not worker_id:
        raise ValueError("worker_id wajib diisi")
    validate_worker_target(worker_id)

    now = datetime.utcnow()
    lease_until = now + timedelta(seconds=max(60, int(lease_seconds)))
    auto_cutoff = now - timedelta(seconds=max(0, int(auto_after_seconds)))
    if worker_id == "pi" and auto_after_seconds > 0:
        target_filter = or_(
            Job.worker_target == "pi",
            and_(Job.worker_target == "auto", Job.created_at <= auto_cutoff),
        )
    else:
        target_filter = or_(Job.worker_target == worker_id, Job.worker_target == "auto")

    query = (
        db.query(Job)
        .filter(
            Job.job_type == "PULL",
            Job.status == "PENDING",
            target_filter,
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
        .with_for_update(skip_locked=True)
    )
    if worker_id == "pi":
        query = query.filter(Job.platform.in_(PI_PULL_PLATFORMS))
    job = query.first()
    if not job:
        db.rollback()
        return None

    job.claimed_by = worker_id
    job.lease_expires_at = lease_until
    job.current_step = f"Diambil worker {worker_id}..."
    db.commit()
    db.refresh(job)
    return job


def recover_expired_pull_leases(db) -> int:
    """Return jobs from dead workers to PENDING without touching active jobs."""
    now = datetime.utcnow()
    jobs = (
        db.query(Job)
        .filter(
            Job.job_type == "PULL",
            Job.status == "RUNNING",
            Job.lease_expires_at.isnot(None),
            Job.lease_expires_at < now,
        )
        .all()
    )
    for job in jobs:
        job.status = "PENDING"
        job.claimed_by = None
        job.lease_expires_at = None
        job.current_step = "Dikembalikan ke antrean setelah worker terputus."
    if jobs:
        db.commit()
    return len(jobs)
