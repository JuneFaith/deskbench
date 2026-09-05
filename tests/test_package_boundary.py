"""Tests for the Deskbench package boundary."""

import subprocess
import sys


def test_core_package_imports_without_tix() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import deskbench.contracts"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_tix_adapter_is_not_imported_by_core() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import deskbench.contracts; "
            "assert 'deskbench.adapters.tix_graph' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
