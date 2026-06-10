"""
Thin wrapper around requests for authenticated calls to the VardrMap API.
All methods raise requests.HTTPError on non-2xx responses.
"""
from typing import Any, Optional

import requests


class VardrMapClient:
    def __init__(self, api_url: str, api_key: str):
        self.base = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        r = self.session.get(self._url(path), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: Optional[dict] = None, files: Optional[dict] = None, data: Optional[dict] = None) -> Any:
        r = self.session.post(self._url(path), json=json, files=files, data=data, timeout=60)
        r.raise_for_status()
        return r.json()

    def whoami(self) -> dict:
        return self.get("/me")

    def programs(self) -> list[dict]:
        return self.get("/programs").get("programs", [])

    def program(self, program_id: str) -> dict:
        return self.get(f"/programs/{program_id}")

    def scope(self, program_id: str) -> dict:
        """Returns {"in": [...], "out": [...]} scope lists."""
        return self.program(program_id).get("scope", {"in": [], "out": []})

    def recon(self, program_id: str, limit: int = 100, status_code: Optional[int] = None) -> list[dict]:
        params: dict = {"limit": limit, "offset": 0}
        if status_code is not None:
            params["status_code"] = status_code
        return self.get(f"/programs/{program_id}/recon", params=params).get("recon", [])

    def import_file(self, program_id: str, tool_type: str, file_path: str) -> dict:
        with open(file_path, "rb") as fh:
            return self.post(
                f"/programs/{program_id}/imports",
                files={"file": (file_path, fh, "application/json")},
                data={"tool_type": tool_type},
            )

    # ------------------------------------------------------------------
    # Scan jobs (job queue for UI-initiated scans)
    # ------------------------------------------------------------------

    def pending_jobs(self) -> list[dict]:
        """Return all pending jobs owned by the authenticated user."""
        return self.get("/jobs/pending").get("jobs", [])

    def claim_job(self, job_id: str) -> dict:
        """Mark a job as running (claim it before executing)."""
        return self.patch(f"/jobs/{job_id}", json={"status": "running"})

    def complete_job(self, job_id: str, status: str, error: str = "") -> dict:
        """Mark a job done or failed."""
        payload: dict = {"status": status}
        if error:
            payload["error_message"] = error
        return self.patch(f"/jobs/{job_id}", json=payload)

    def patch(self, path: str, json: Optional[dict] = None) -> Any:
        r = self.session.patch(self._url(path), json=json, timeout=30)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Runner heartbeat
    # ------------------------------------------------------------------

    def send_heartbeat(self, payload: dict) -> dict:
        """Post runner status (hostname, version, os, tools) to the backend."""
        return self.post("/runner/heartbeat", json=payload)
