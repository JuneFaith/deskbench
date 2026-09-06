"""Environment probing and cleanup for Tix deployments."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


class EnvironmentHandler(BaseModel):
    """Profile and current load of an agent handler."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    current_load: int = 0
    max_load: int = 5
    active: bool = True
    skills: list[str] = Field(default_factory=list)

    @property
    def is_saturated(self) -> bool:
        """Return True if the handler is active and at or above max load."""
        return self.active and self.current_load >= self.max_load


class EnvironmentStatus(BaseModel):
    """Snapshot of target environment health and handler capacity."""

    model_config = ConfigDict(extra="ignore")

    healthy: bool
    base_url: str
    handlers: list[EnvironmentHandler] = Field(default_factory=list)
    saturated_handlers: list[EnvironmentHandler] = Field(default_factory=list)
    error: str | None = None


_PURGE_SQL = (
    "DELETE FROM ticket_events WHERE ticket_id IN "
    "(SELECT id FROM tickets WHERE channel = 'api');\n"
    "DELETE FROM ticket_feedback WHERE ticket_id IN "
    "(SELECT id FROM tickets WHERE channel = 'api');\n"
    "DELETE FROM pgvector_ticket_vectors WHERE ticket_id IN "
    "(SELECT id FROM tickets WHERE channel = 'api');\n"
    "DELETE FROM checkpoint_writes WHERE thread_id IN "
    "(SELECT id FROM tickets WHERE channel = 'api');\n"
    "DELETE FROM checkpoint_blobs WHERE thread_id IN "
    "(SELECT id FROM tickets WHERE channel = 'api');\n"
    "DELETE FROM checkpoints WHERE thread_id IN "
    "(SELECT id FROM tickets WHERE channel = 'api');\n"
    "DELETE FROM tickets WHERE channel = 'api';\n"
    "UPDATE handlers SET current_load = 0;\n"
)


def _resolve_tix_repo_path(tix_repo_path: str | Path | None) -> Path | None:
    if tix_repo_path:
        p = Path(tix_repo_path).resolve()
        if p.is_dir():
            return p
    env_path = os.environ.get("TIX_REPO_PATH")
    if env_path:
        p = Path(env_path).resolve()
        if p.is_dir():
            return p
    cwd = Path.cwd().resolve()
    for candidate in [
        cwd / "tix",
        cwd.parent / "tix",
        Path("/home/zev/workspace/tix"),
    ]:
        if candidate.is_dir() and (candidate / "backend").is_dir():
            return candidate
    return None


async def probe_environment(
    base_url: str,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> EnvironmentStatus:
    """Probe target environment health, authentication, and handler loads.

    Args:
        base_url: Tix root or API URL.
        token: Existing bearer token.
        username: Login username if token is not provided.
        password: Login password if token is not provided.
        client: Optional pre-configured httpx.AsyncClient.

    Returns:
        An EnvironmentStatus summarizing health and handler capacity.
    """
    if client is not None:
        return await _probe_environment_impl(
            client=client,
            base_url=base_url,
            token=token,
            username=username,
            password=password,
        )
    async with httpx.AsyncClient(trust_env=False, timeout=15.0) as owned_client:
        return await _probe_environment_impl(
            client=owned_client,
            base_url=base_url,
            token=token,
            username=username,
            password=password,
        )


async def _probe_environment_impl(
    client: httpx.AsyncClient,
    base_url: str,
    token: str | None,
    username: str | None,
    password: str | None,
) -> EnvironmentStatus:
    clean_base = base_url.rstrip("/")
    if clean_base.endswith("/api"):
        root_url = clean_base[:-4]
        api_url = clean_base
    else:
        root_url = clean_base
        api_url = f"{clean_base}/api"

    # 1. Checks {base_url}/health
    healthy = False
    error_detail: str | None = None
    try:
        health_resp = await client.get(f"{clean_base}/health")
        if health_resp.status_code == 404 and clean_base != root_url:
            health_resp = await client.get(f"{root_url}/health")
        elif health_resp.status_code == 404 and clean_base == root_url:
            health_resp = await client.get(f"{api_url}/health")

        if health_resp.status_code == 200:
            try:
                data = health_resp.json()
                if isinstance(data, dict):
                    status_val = str(data.get("status", "")).lower()
                    if status_val in ("healthy", "ok"):
                        healthy = True
                    elif "status" not in data and data.get("healthy") is True:
                        healthy = True
                    elif not status_val and not data:
                        healthy = True
                    elif status_val in ("degraded", "unhealthy", "error"):
                        healthy = False
                        error_detail = f"service is {status_val}"
                    else:
                        healthy = True
                else:
                    healthy = True
            except Exception:
                healthy = True
        else:
            healthy = False
            error_detail = f"health check returned HTTP {health_resp.status_code}"
    except Exception as exc:
        return EnvironmentStatus(
            healthy=False,
            base_url=base_url,
            handlers=[],
            saturated_handlers=[],
            error=str(exc),
        )

    # 2. Logs in if username/password provided and token is None
    active_token = token
    if active_token is None and username and password is not None:
        try:
            login_resp = await client.post(
                f"{api_url}/auth/login",
                json={"username": username, "password": password},
            )
            if login_resp.status_code == 200:
                login_data = login_resp.json()
                if isinstance(login_data, dict):
                    active_token = login_data.get("access_token") or login_data.get("token")
            else:
                if error_detail is None:
                    error_detail = f"login failed: HTTP {login_resp.status_code}"
        except Exception as exc:
            if error_detail is None:
                error_detail = f"login request error: {exc}"

    # 3. Fetches {base_url}/api/handlers with Bearer token
    handlers: list[EnvironmentHandler] = []
    saturated_handlers: list[EnvironmentHandler] = []
    headers: dict[str, str] = {}
    if active_token:
        headers["Authorization"] = f"Bearer {active_token}"

    try:
        handlers_resp = await client.get(f"{api_url}/handlers", headers=headers)
        if handlers_resp.status_code == 200:
            resp_data = handlers_resp.json()
            raw_list = (
                resp_data.get("handlers", [])
                if isinstance(resp_data, dict)
                else resp_data
            )
            if isinstance(raw_list, list):
                for item in raw_list:
                    if isinstance(item, dict):
                        handler = EnvironmentHandler.model_validate(item)
                        handlers.append(handler)
                        # 4. Detects saturated_handlers (current_load >= max_load and active)
                        if handler.is_saturated:
                            saturated_handlers.append(handler)
        else:
            if error_detail is None:
                error_detail = f"fetch handlers failed: HTTP {handlers_resp.status_code}"
    except Exception as exc:
        if error_detail is None:
            error_detail = f"fetch handlers error: {exc}"

    return EnvironmentStatus(
        healthy=healthy,
        base_url=base_url,
        handlers=handlers,
        saturated_handlers=saturated_handlers,
        error=error_detail,
    )


async def clean_environment(
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    container_name: str = "tix_pg_dev",
    tix_repo_path: str | Path | None = None,
) -> dict[str, Any]:
    """Purge API test tickets and reset handler load in the environment.

    First attempts psql execution within a Docker or Podman container.
    Falls back to invoking the Tix reconcile CLI if the repository is located.
    If base_url is provided, re-probes the environment and attaches status.

    Returns:
        Dict with cleanup results, method used, and optional status probe.
    """
    cleaned = False
    method = "none"
    output = ""
    container_err = ""
    cli_err = ""

    container_cli = shutil.which("podman") or shutil.which("docker")
    if container_cli:
        user = os.environ.get("POSTGRES_USER", "tix_owner")
        db = os.environ.get("POSTGRES_DB", "tix_db")
        cmd = [
            container_cli,
            "exec",
            container_name,
            "psql",
            "-U",
            user,
            "-d",
            db,
            "-c",
            _PURGE_SQL,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=30
            )
            if proc.returncode == 0:
                cleaned = True
                method = "container_psql"
                output = proc.stdout.strip()
            else:
                container_err = (
                    proc.stderr.strip() or f"process exited with {proc.returncode}"
                )
        except Exception as exc:
            container_err = str(exc)
    else:
        container_err = "neither podman nor docker found in PATH"

    if not cleaned:
        repo_dir = _resolve_tix_repo_path(tix_repo_path)
        if repo_dir:
            config_candidate = repo_dir / ".local/tix-dev/tix.yaml"
            if not config_candidate.is_file():
                config_candidate = repo_dir / "tix.yaml"

            cli_cmd = [
                "uv",
                "run",
                "--project",
                "backend",
                "python",
                "-m",
                "src.cli.commands",
                "reconcile",
                "--purge-api-tickets",
            ]
            if config_candidate.is_file():
                cli_cmd.extend(["--config", str(config_candidate)])

            try:
                proc = subprocess.run(
                    cli_cmd,
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if proc.returncode == 0:
                    cleaned = True
                    method = "tix_reconcile_cli"
                    output = proc.stdout.strip()
                else:
                    cli_err = (
                        proc.stderr.strip() or f"process exited with {proc.returncode}"
                    )
            except Exception as exc:
                cli_err = str(exc)
        else:
            cli_err = "tix repository path could not be located"

    result: dict[str, Any] = {
        "cleaned": cleaned,
        "method": method,
    }
    if cleaned:
        result["output"] = output
    else:
        result["error"] = f"container error: {container_err}; cli error: {cli_err}"

    if base_url:
        probe_token = (
            token
            or os.environ.get("DESKBENCH_TIX_TOKEN")
            or os.environ.get("SERVICEDESKBENCH_TIX_TOKEN")
        )
        probe_user = (
            username
            or os.environ.get("DESKBENCH_TIX_USERNAME")
            or os.environ.get("SERVICEDESKBENCH_TIX_USERNAME")
        )
        probe_pass = (
            password
            or os.environ.get("DESKBENCH_TIX_PASSWORD")
            or os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD")
        )
        status = await probe_environment(
            base_url=base_url,
            token=probe_token,
            username=probe_user,
            password=probe_pass,
        )
        result["status"] = status.model_dump()

    return result
