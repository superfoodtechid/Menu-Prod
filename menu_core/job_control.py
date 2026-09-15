import threading
import logging

logger = logging.getLogger("FoodMasterAPI.JobControl")

_CANCELLED_JOB_IDS = set()
_CANCEL_CALLBACKS = {}
_lock = threading.Lock()

class JobCancelledException(Exception):
    """Raised when an operation is cancelled by the user."""
    pass

def register_job_canceller(job_id, callback) -> None:
    """
    Registers a callable callback to be invoked immediately if the job is cancelled.
    If the job is already marked as cancelled, the callback is invoked immediately.
    """
    if not job_id or not callable(callback):
        return
    jid_str = str(job_id)
    already_cancelled = False
    with _lock:
        if jid_str in _CANCELLED_JOB_IDS:
            already_cancelled = True
        else:
            if jid_str not in _CANCEL_CALLBACKS:
                _CANCEL_CALLBACKS[jid_str] = []
            _CANCEL_CALLBACKS[jid_str].append(callback)

    if already_cancelled:
        try:
            callback()
        except Exception as e:
            logger.warning(f"Error immediately invoking cancel callback for {jid_str}: {e}")

def unregister_job_canceller(job_id, callback=None) -> None:
    """Unregisters a specific callback or all callbacks for a job."""
    if not job_id:
        return
    jid_str = str(job_id)
    with _lock:
        if callback is None:
            _CANCEL_CALLBACKS.pop(jid_str, None)
        elif jid_str in _CANCEL_CALLBACKS:
            try:
                _CANCEL_CALLBACKS[jid_str].remove(callback)
            except ValueError:
                pass
            if not _CANCEL_CALLBACKS[jid_str]:
                _CANCEL_CALLBACKS.pop(jid_str, None)

def cancel_job(job_id) -> None:
    """Marks a job ID as cancelled in memory and immediately triggers all registered cancellation callbacks."""
    if not job_id:
        return
    jid_str = str(job_id)
    callbacks = []
    with _lock:
        _CANCELLED_JOB_IDS.add(jid_str)
        callbacks = list(_CANCEL_CALLBACKS.pop(jid_str, []))

    for cb in callbacks:
        try:
            cb()
        except Exception as e:
            logger.warning(f"Error executing cancel callback for job {jid_str}: {e}")

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

def check_job_cancelled(job_id, db=None) -> None:
    """Helper that raises JobCancelledException if the job was cancelled."""
    if is_job_cancelled(job_id, db=db):
        raise JobCancelledException(f"Job {job_id} telah dibatalkan oleh pengguna.")

def clear_cancelled_job(job_id) -> None:
    """Removes a job ID from the cancelled registry if needed."""
    if not job_id:
        return
    jid_str = str(job_id)
    with _lock:
        _CANCELLED_JOB_IDS.discard(jid_str)
        _CANCEL_CALLBACKS.pop(jid_str, None)

