import threading

_CANCELLED_JOB_IDS = set()
_lock = threading.Lock()

def cancel_job(job_id) -> None:
    """Marks a job ID as cancelled in memory for immediate detection by running workers."""
    if not job_id:
        return
    with _lock:
        _CANCELLED_JOB_IDS.add(str(job_id))

def is_job_cancelled(job_id, db=None) -> bool:
    """
    Checks if a job has been cancelled, checking both in-memory registry and database.
    """
    if not job_id:
        return False
    jid_str = str(job_id)
    with _lock:
        if jid_str in _CANCELLED_JOB_IDS:
            return True

    if db:
        try:
            from menu_core.models import Job
            db.expire_all()
            j = db.query(Job).filter(Job.id == job_id).first()
            if j and j.status == "CANCELLED":
                with _lock:
                    _CANCELLED_JOB_IDS.add(jid_str)
                return True
        except Exception:
            pass

    return False

def clear_cancelled_job(job_id) -> None:
    """Removes a job ID from the cancelled registry if needed."""
    if not job_id:
        return
    with _lock:
        _CANCELLED_JOB_IDS.discard(str(job_id))

