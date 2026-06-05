"""HTTP client wrapper for backend API"""
import httpx
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class APIClient:
    """HTTP client wrapper for backend API"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        """
        Initialize API client.

        Args:
            base_url: Base URL (e.g., "http://localhost:8000")
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Send GET request.

        Args:
            path: API path (e.g., "/api/tasks/123")
            params: Query parameters

        Returns:
            Response JSON data

        Raises:
            TimeoutError: Request timed out
            APIError: HTTP error occurred
        """
        url = f"{self.base_url}{path}"
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {url}")
            raise TimeoutError(f"Request to {url} timed out") from e
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {url}")
            data = e.response.json() if e.response.headers.get("content-type") == "application/json" else {}
            raise APIError(e.response.status_code, data.get("message", str(e))) from e

    def post(self, path: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Send POST request.

        Args:
            path: API path
            json: JSON body

        Returns:
            Response JSON data

        Raises:
            TimeoutError: Request timed out
            APIError: HTTP error occurred
        """
        url = f"{self.base_url}{path}"
        try:
            response = self.client.post(url, json=json)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {url}")
            raise TimeoutError(f"Request to {url} timed out") from e
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {url}")
            data = e.response.json() if e.response.headers.get("content-type") == "application/json" else {}
            raise APIError(e.response.status_code, data.get("message", str(e))) from e

    def delete(self, path: str) -> Dict[str, Any]:
        """
        Send DELETE request.

        Args:
            path: API path

        Returns:
            Response JSON data

        Raises:
            TimeoutError: Request timed out
            APIError: HTTP error occurred
        """
        url = f"{self.base_url}{path}"
        try:
            response = self.client.delete(url)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {url}")
            raise TimeoutError(f"Request to {url} timed out") from e
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {url}")
            data = e.response.json() if e.response.headers.get("content-type") == "application/json" else {}
            raise APIError(e.response.status_code, data.get("message", str(e))) from e

    def close(self):
        """Close HTTP client"""
        self.client.close()


class APIError(Exception):
    """API error with status code and message"""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")
