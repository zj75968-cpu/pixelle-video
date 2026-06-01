"""Task API interface"""
from typing import Optional
from pixelle_video.web.api.client import APIClient, APIError
import logging

logger = logging.getLogger(__name__)


class TaskAPI:
    """Task API interface"""

    def __init__(self, client: APIClient):
        """
        Initialize Task API.

        Args:
            client: API client instance
        """
        self.client = client

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """
        Get task status and result.

        Args:
            task_id: Task identifier

        Returns:
            TaskResponse dict or None if not found
        """
        try:
            return self.client.get(f"/api/tasks/{task_id}")
        except APIError as e:
            if e.status_code == 404:
                logger.warning(f"Task {task_id} not found")
                return None
            raise

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task.

        Args:
            task_id: Task identifier

        Returns:
            True if cancelled, False if not found or already completed
        """
        try:
            response = self.client.delete(f"/api/tasks/{task_id}")
            return response.get("success", False)
        except APIError as e:
            if e.status_code == 404:
                logger.warning(f"Task {task_id} not found or already completed")
                return False
            raise
