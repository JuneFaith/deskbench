"""Tests for environment probing, cleanup, and CLI commands."""

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pytest import CaptureFixture

from deskbench.cli import build_parser, main
from deskbench.environment import (
    EnvironmentHandler,
    EnvironmentStatus,
    clean_environment,
    probe_environment,
)


def test_environment_handler_model() -> None:
    handler = EnvironmentHandler(
        id="h1",
        name="王工",
        current_load=4,
        max_load=4,
        active=True,
    )
    assert handler.is_saturated is True

    unsaturated = EnvironmentHandler(
        id="h2",
        name="张工",
        current_load=2,
        max_load=5,
        active=True,
    )
    assert unsaturated.is_saturated is False

    inactive_at_max = EnvironmentHandler(
        id="h3",
        name="李工",
        current_load=5,
        max_load=5,
        active=False,
    )
    assert inactive_at_max.is_saturated is False


@pytest.mark.anyio
async def test_probe_environment_healthy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        if path == "/api/handlers":
            assert request.headers.get("Authorization") == "Bearer test-token"
            return httpx.Response(
                200,
                json={
                    "handlers": [
                        {
                            "id": "h1",
                            "name": "王工",
                            "current_load": 1,
                            "max_load": 4,
                            "active": True,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status = await probe_environment(
        "http://testserver",
        token="test-token",
        client=client,
    )

    assert status.healthy is True
    assert len(status.handlers) == 1
    assert status.handlers[0].name == "王工"
    assert len(status.saturated_handlers) == 0
    assert status.error is None


@pytest.mark.anyio
async def test_probe_environment_auth_login() -> None:
    login_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_called
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        if path == "/api/auth/login":
            login_called = True
            body = json.loads(request.content)
            assert body["username"] == "supervisor"
            assert body["password"] == "super-pass"
            return httpx.Response(200, json={"access_token": "logged-in-jwt"})
        if path == "/api/handlers":
            assert request.headers.get("Authorization") == "Bearer logged-in-jwt"
            return httpx.Response(200, json={"handlers": []})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status = await probe_environment(
        "http://testserver",
        username="supervisor",
        password="super-pass",
        client=client,
    )

    assert login_called is True
    assert status.healthy is True
    assert status.handlers == []


@pytest.mark.anyio
async def test_probe_environment_saturated_detection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        if path == "/api/handlers":
            return httpx.Response(
                200,
                json={
                    "handlers": [
                        {
                            "id": "h1",
                            "name": "王工",
                            "current_load": 4,
                            "max_load": 4,
                            "active": True,
                        },
                        {
                            "id": "h2",
                            "name": "张工",
                            "current_load": 2,
                            "max_load": 5,
                            "active": True,
                        },
                        {
                            "id": "h3",
                            "name": "李工",
                            "current_load": 5,
                            "max_load": 5,
                            "active": False,
                        },
                    ]
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status = await probe_environment(
        "http://testserver",
        token="tok",
        client=client,
    )

    assert status.healthy is True
    assert len(status.handlers) == 3
    assert len(status.saturated_handlers) == 1
    assert status.saturated_handlers[0].id == "h1"


@pytest.mark.anyio
async def test_probe_environment_unhealthy_service() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(500, json={"status": "unhealthy"})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status = await probe_environment("http://testserver", client=client)

    assert status.healthy is False
    assert status.error is not None
    assert "500" in status.error


@pytest.mark.anyio
async def test_clean_environment_container_success() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/podman"),
        patch(
            "subprocess.run",
            return_value=CompletedProcess(
                args=[], returncode=0, stdout="DELETE 12\nUPDATE 4"
            ),
        ) as mock_sub,
    ):
        result = await clean_environment(container_name="test_pg")

        assert result["cleaned"] is True
        assert result["method"] == "container_psql"
        assert "DELETE 12" in result["output"]
        mock_sub.assert_called_once()
        cmd = mock_sub.call_args[0][0]
        assert cmd[0] == "/usr/bin/podman"
        assert cmd[1] == "exec"
        assert cmd[2] == "test_pg"


@pytest.mark.anyio
async def test_clean_environment_fallback_to_reconcile_cli(tmp_path: Path) -> None:
    tix_dir = tmp_path / "tix"
    (tix_dir / "backend").mkdir(parents=True)
    (tix_dir / "tix.yaml").write_text("config: true\n")

    # First call fails (container), second call succeeds (tix reconcile)
    call_count = 0

    def mock_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CompletedProcess(
                args=[], returncode=1, stderr="container not running"
            )
        return CompletedProcess(
            args=[], returncode=0, stdout="Reconciled handler loads"
        )

    with (
        patch("shutil.which", return_value="/usr/bin/podman"),
        patch("subprocess.run", side_effect=mock_run),
        patch("deskbench.environment._resolve_tix_repo_path", return_value=tix_dir),
    ):
        result = await clean_environment(tix_repo_path=tix_dir)

        assert result["cleaned"] is True
        assert result["method"] == "tix_reconcile_cli"
        assert "Reconciled handler loads" in result["output"]


@pytest.mark.anyio
async def test_clean_environment_with_base_url_probes() -> None:
    mock_status = EnvironmentStatus(
        healthy=True,
        base_url="http://testserver",
        handlers=[],
        saturated_handlers=[],
    )

    with (
        patch("shutil.which", return_value="/usr/bin/podman"),
        patch(
            "subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="OK"),
        ),
        patch(
            "deskbench.environment.probe_environment",
            new_callable=AsyncMock,
            return_value=mock_status,
        ) as mock_probe,
    ):
        result = await clean_environment(base_url="http://testserver")

        assert result["cleaned"] is True
        assert "status" in result
        assert result["status"]["healthy"] is True
        mock_probe.assert_awaited_once()


@pytest.mark.anyio
async def test_clean_environment_all_fail() -> None:
    with (
        patch("shutil.which", return_value=None),
        patch("deskbench.environment._resolve_tix_repo_path", return_value=None),
    ):
        result = await clean_environment()

        assert result["cleaned"] is False
        assert result["method"] == "none"
        assert "error" in result


def test_cli_env_parser() -> None:
    parser = build_parser()
    status_args = parser.parse_args(["env", "status", "--url", "http://tix"])
    assert status_args.command == "env"
    assert status_args.env_command == "status"
    assert status_args.url == "http://tix"

    clean_args = parser.parse_args(["env", "clean", "--container", "pg_custom"])
    assert clean_args.command == "env"
    assert clean_args.env_command == "clean"
    assert clean_args.container == "pg_custom"


def test_cli_env_status_command_text(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DESKBENCH_TIX_URL", "http://mock-tix")

    mock_status = EnvironmentStatus(
        healthy=True,
        base_url="http://mock-tix",
        handlers=[
            EnvironmentHandler(
                id="wanggong",
                name="王工",
                current_load=4,
                max_load=4,
                active=True,
            )
        ],
        saturated_handlers=[
            EnvironmentHandler(
                id="wanggong",
                name="王工",
                current_load=4,
                max_load=4,
                active=True,
            )
        ],
    )

    with patch(
        "deskbench.environment.probe_environment",
        new_callable=AsyncMock,
        return_value=mock_status,
    ):
        exit_code = main(["env", "status"])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Environment (http://mock-tix): healthy" in out
        assert "王工" in out
        assert "[SATURATED]" in out
        assert "Warning: 1 handler(s) saturated!" in out


def test_cli_env_status_command_json(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_status = EnvironmentStatus(
        healthy=True,
        base_url="http://mock-tix",
        handlers=[],
        saturated_handlers=[],
    )

    with patch(
        "deskbench.environment.probe_environment",
        new_callable=AsyncMock,
        return_value=mock_status,
    ):
        exit_code = main(["env", "status", "--url", "http://mock-tix", "--json"])

        assert exit_code == 0
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["healthy"] is True
        assert parsed["base_url"] == "http://mock-tix"


def test_cli_env_clean_command_text(capsys: CaptureFixture[str]) -> None:
    mock_result = {
        "cleaned": True,
        "method": "container_psql",
        "output": "Purged 10 tickets",
    }

    with patch(
        "deskbench.environment.clean_environment",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        exit_code = main(["env", "clean", "--url", "http://mock-tix"])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Environment cleaned successfully using container_psql." in out


def test_cli_env_clean_command_json(capsys: CaptureFixture[str]) -> None:
    mock_result = {
        "cleaned": True,
        "method": "tix_reconcile_cli",
        "output": "Reset all handler loads to 0",
    }

    with patch(
        "deskbench.environment.clean_environment",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        exit_code = main(["env", "clean", "--json"])

        assert exit_code == 0
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["cleaned"] is True
        assert parsed["method"] == "tix_reconcile_cli"


def test_cli_run_pre_clean_and_saturated_warning(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DESKBENCH_TIX_URL", "http://127.0.0.1:8000")
    dataset = tmp_path / "cases.yaml"
    dataset.write_text("- id: case-1\n  expected:\n    final_status: closed\n")

    mock_clean = {
        "cleaned": True,
        "method": "container_psql",
    }
    mock_status = EnvironmentStatus(
        healthy=True,
        base_url="http://127.0.0.1:8000",
        handlers=[],
        saturated_handlers=[
            EnvironmentHandler(
                id="wanggong",
                name="王工",
                current_load=4,
                max_load=4,
                active=True,
            )
        ],
    )

    from deskbench.reporting.json_report import ReportPaths

    report_dir = tmp_path / "reports" / "2026-09-06T000000Z"
    report_dir.mkdir(parents=True)

    with (
        patch(
            "deskbench.environment.clean_environment",
            new_callable=AsyncMock,
            return_value=mock_clean,
        ) as mock_clean_fn,
        patch(
            "deskbench.environment.probe_environment",
            new_callable=AsyncMock,
            return_value=mock_status,
        ) as mock_probe_fn,
        patch(
            "deskbench.cli.run_dataset",
            new_callable=AsyncMock,
            return_value=ReportPaths(report_dir),
        ),
    ):
        exit_code = main(["run", "--dataset", str(dataset), "--pre-clean"])

        assert exit_code == 0
        mock_clean_fn.assert_awaited_once()
        mock_probe_fn.assert_awaited_once()
        captured = capsys.readouterr()
        assert "warning: 1 handler(s) are saturated: 王工 (4/4)" in captured.out
