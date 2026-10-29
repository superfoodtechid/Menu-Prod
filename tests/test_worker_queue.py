from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from menu_core.database import Base, Job
from menu_core.worker_queue import (
    claim_next_pull_job,
    recover_expired_pull_leases,
    validate_worker_target,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_claim_respects_worker_target_and_auto():
    db = make_session()
    db.add_all([
        Job(job_type="PULL", platform="gofood", status="PENDING", worker_target="pi"),
        Job(job_type="PULL", platform="grab", status="PENDING", worker_target="auto"),
    ])
    db.commit()

    vm_job = claim_next_pull_job(db, "vm1")
    assert vm_job.worker_target == "auto"
    pi_job = claim_next_pull_job(db, "pi")
    assert pi_job.worker_target == "pi"
    assert vm_job.id != pi_job.id


def test_expired_lease_is_returned_to_queue():
    db = make_session()
    job = Job(
        job_type="PULL",
        platform="shopee",
        status="RUNNING",
        worker_target="pi",
        claimed_by="pi",
        lease_expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db.add(job)
    db.commit()

    assert recover_expired_pull_leases(db) == 1
    db.refresh(job)
    assert job.status == "PENDING"
    assert job.claimed_by is None
    assert job.lease_expires_at is None


def test_worker_target_validation():
    assert validate_worker_target("PI") == "pi"
    try:
        validate_worker_target("raspberry")
    except ValueError as exc:
        assert "worker_target" in str(exc)
    else:
        raise AssertionError("invalid worker target should be rejected")


def test_pi_only_claims_shopee_grab():
    db = make_session()
    db.add_all([
        Job(job_type="PULL", platform="gofood", status="PENDING", worker_target="auto"),
        Job(job_type="PULL", platform="shopee", status="PENDING", worker_target="auto"),
    ])
    db.commit()

    job = claim_next_pull_job(db, "pi", auto_after_seconds=0)
    assert job.platform == "shopee"
