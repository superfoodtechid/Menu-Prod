import os
import unittest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from main import (
    COMBINE_STATUS,
    RetryCombineC5Request,
    retry_combine_c5_endpoint,
    _trigger_bg_combined_upload,
)


class TestCombineC5Retry(unittest.TestCase):

    def setUp(self):
        COMBINE_STATUS.clear()

    @patch("main._trigger_bg_combined_upload")
    @patch("os.path.exists", return_value=True)
    def test_retry_existing_combine_id_reuploads(self, mock_exists, mock_trigger):
        cid = "test-combine-123"
        COMBINE_STATUS[cid] = {
            "status": "FAILED",
            "excel_path": "/tmp/test.xlsx",
            "excel_filename": "test.xlsx",
            "clean_owner_name": "Test Owner",
            "drive_filename": "test.xlsx",
            "photo_job_ids": ["job-1"],
            "gspread_url": None,
            "error": "Timeout",
        }

        req = RetryCombineC5Request(combine_id=cid)
        res = retry_combine_c5_endpoint(req, db=MagicMock())

        self.assertTrue(res["ok"])
        self.assertEqual(res["combine_id"], cid)
        self.assertEqual(COMBINE_STATUS[cid]["status"], "UPLOADING")
        mock_trigger.assert_called_once_with(
            combine_id=cid,
            combined_path="/tmp/test.xlsx",
            clean_owner_name="Test Owner",
            drive_filename="test.xlsx",
            photo_job_ids=["job-1"],
        )

    @patch("main._execute_combine_and_upload")
    def test_retry_with_explicit_job_ids(self, mock_exec):
        mock_exec.return_value = {"ok": True, "combine_id": "new-cid-456"}
        req = RetryCombineC5Request(job_ids=["job-1", "job-2"], outlet_name="Outlet ABC")
        res = retry_combine_c5_endpoint(req, db=MagicMock())

        self.assertTrue(res["ok"])
        mock_exec.assert_called_once()
        args, _ = mock_exec.call_args
        self.assertEqual(args[0], ["job-1", "job-2"])
        self.assertEqual(args[1], "Outlet ABC")

    @patch("main._execute_combine_and_upload")
    def test_retry_auto_discover_recent_jobs(self, mock_exec):
        mock_exec.return_value = {"ok": True, "combine_id": "auto-cid-789"}
        mock_db = MagicMock()

        job1 = MagicMock()
        job1.id = uuid.uuid4()
        job1.result_metadata = {"excel_path": "/tmp/job1.xlsx"}
        job1.completed_at = datetime(2026, 10, 26, 17, 10, 0)

        job2 = MagicMock()
        job2.id = uuid.uuid4()
        job2.result_metadata = {"excel_path": "/tmp/job2.xlsx"}
        job2.completed_at = datetime(2026, 10, 26, 17, 5, 0)

        mock_query = mock_db.query.return_value.filter.return_value.order_by.return_value
        mock_query.limit.return_value.all.return_value = [job1, job2]

        req = RetryCombineC5Request()
        res = retry_combine_c5_endpoint(req, db=mock_db)

        self.assertTrue(res["ok"])
        mock_exec.assert_called_once()
        args, _ = mock_exec.call_args
        self.assertEqual(args[0], [str(job1.id), str(job2.id)])

    def test_retry_auto_discover_raises_if_no_jobs(self):
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value.filter.return_value.order_by.return_value
        mock_query.limit.return_value.all.return_value = []

        req = RetryCombineC5Request()
        with self.assertRaises(HTTPException) as ctx:
            retry_combine_c5_endpoint(req, db=mock_db)

        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
