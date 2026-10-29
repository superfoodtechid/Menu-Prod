"""Run PULL jobs outside the API process.

VM1 runs this as the primary worker. A Raspberry Pi can run the same process
with WORKER_ID=pi and claim only jobs targeted at Pi or auto.
"""

import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

from menu_core.database import SessionLocal, init_db
from menu_core.worker_queue import claim_next_pull_job, recover_expired_pull_leases


def _heartbeat(job_id, worker_id, stop_event, lease_seconds):
    interval = max(15, min(60, lease_seconds // 3))
    while not stop_event.wait(interval):
        db = SessionLocal()
        try:
            from menu_core.database import Job
            job = db.query(Job).filter(
                Job.id == job_id,
                Job.claimed_by == worker_id,
                Job.status.in_(["PENDING", "RUNNING"]),
            ).first()
            if not job:
                return
            from datetime import datetime, timedelta
            job.lease_expires_at = datetime.utcnow() + timedelta(seconds=lease_seconds)
            db.commit()
        finally:
            db.close()


def run_worker():
    worker_id = os.getenv("WORKER_ID", "vm1").strip().lower()
    poll_seconds = max(1, int(os.getenv("WORKER_POLL_SECONDS", "3")))
    lease_seconds = max(60, int(os.getenv("WORKER_LEASE_SECONDS", "7200")))
    auto_after_seconds = max(0, int(os.getenv("WORKER_AUTO_DELAY_SECONDS", "0")))
    if worker_id not in {"vm1", "pi"}:
        raise SystemExit("WORKER_ID harus vm1 atau pi")

    init_db()
    print(f"FoodMaster worker aktif: {worker_id}")
    while True:
        db = SessionLocal()
        try:
            recover_expired_pull_leases(db)
            job = claim_next_pull_job(db, worker_id, lease_seconds, auto_after_seconds)
        finally:
            db.close()

        if not job:
            time.sleep(poll_seconds)
            continue

        print(f"Worker {worker_id} menjalankan PULL {job.id} ({job.platform})")
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat,
            args=(job.id, worker_id, heartbeat_stop, lease_seconds),
            daemon=True,
        )
        heartbeat.start()
        try:
            from main import run_pull_job
            run_pull_job(job.id, job.outlet_id)
        except Exception as exc:
            print(f"Worker {worker_id} gagal menjalankan PULL {job.id}: {exc}")
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            db = SessionLocal()
            try:
                from menu_core.database import Job
                current = db.query(Job).filter(Job.id == job.id).first()
                if current and current.claimed_by == worker_id:
                    current.claimed_by = None
                    current.lease_expires_at = None
                    db.commit()
            finally:
                db.close()


if __name__ == "__main__":
    run_worker()
