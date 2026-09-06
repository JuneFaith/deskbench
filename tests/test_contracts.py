"""Tests for Deskbench domain contracts."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from deskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
    ExperimentMetadata,
)
from deskbench.runner.lifecycle import (
    _manifest_source,
    load_cases,
    load_cases_async,
    load_manifest,
)

DATASET = Path("datasets/servicedesk_v1")


def test_case_loads_versioned_approval_fixture() -> None:
    raw = yaml.safe_load((DATASET / "approval.yaml").read_text())[0]

    case = Case.model_validate(raw)

    assert case.id == "security-approval-001"
    assert case.expected.final_status == "closed"
    assert case.policy.forbidden_transitions == ["pending_approval -> closed"]


def test_case_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "", "input": {}})


def test_canonical_state_exposes_business_facts() -> None:
    state = CanonicalState(status="pending_approval", assigned=False)

    assert state.status == "pending_approval"
    assert state.assigned is False


def test_experiment_metadata_requires_reproducibility_fields() -> None:
    metadata = ExperimentMetadata(
        run_id="run-1",
        dataset_version="v1",
        adapter="tix_http",
        tix_commit="abc123",
        agent_version="agent-1",
        model="model-1",
        prompt_version="prompt-1",
        embedding_model="embed-1",
        retrieval_parameters={"min_score": 0.2},
        scorer_version="scorer-1",
    )

    assert metadata.tix_commit == "abc123"
    assert metadata.retrieval_parameters["min_score"] == 0.2
    assert metadata.started_at.tzinfo is not None


def test_agent_run_records_dataset_and_timing_metadata() -> None:
    from datetime import UTC, datetime

    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="test",
        dataset_version="v1",
        started_at=datetime.now(UTC),
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
    )

    assert run.dataset_version == "v1"
    assert run.started_at is not None


def test_case_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "case-1", "unexpected": True})


def test_project_manifest_records_core_and_rag_status() -> None:
    manifest = load_manifest(DATASET)

    assert manifest.status == {
        "core_cases": "available",
        "rag_assets": "available",
    }


def test_dataset_directory_loads_manifest_files_and_provenance(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.yaml").write_text(
        "dataset_version: test_v1\n"
        "source: supplied fixture\n"
        "annotation_notes: labels are deterministic\n"
        "files:\n  - cases.yaml\n"
    )
    (dataset / "cases.yaml").write_text(
        "- id: directory-case\n  expected:\n    final_status: closed\n"
    )

    manifest = load_manifest(dataset)
    cases = load_cases(dataset)

    assert manifest.dataset_version == "test_v1"
    assert cases[0].dataset_version == "test_v1"
    assert cases[0].source == "supplied fixture"
    assert cases[0].annotation_notes == "labels are deterministic"


def test_manifest_file_url_loads_cases(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    cases = tmp_path / "cases.yaml"
    manifest.write_text("dataset_version: file_v1\nfiles:\n  - cases.yaml\n")
    cases.write_text("- id: file-case\n  expected:\n    final_status: closed\n")

    loaded = load_cases(manifest.as_uri())

    assert [case.id for case in loaded] == ["file-case"]


@pytest.mark.anyio
def test_s3_yaml_object_is_not_treated_as_dataset_prefix() -> None:
    assert _manifest_source("s3://bucket/cases.yaml") == "s3://bucket/cases.yaml"


@pytest.mark.anyio
async def test_async_s3_load_reports_remote_read_errors() -> None:
    with pytest.raises(
        RuntimeError,
        match="unable to read remote dataset|asyncio AnyIO backend|deskbench\\[remote\\] extra",
    ):
        await load_cases_async("s3://bucket/dataset")


@pytest.mark.anyio
async def test_async_file_url_directory_loads_cases(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.yaml").write_text(
        "dataset_version: async_v1\nfiles:\n  - cases.yaml\n"
    )
    (dataset / "cases.yaml").write_text(
        "- id: async-case\n  expected:\n    final_status: closed\n"
    )

    loaded = await load_cases_async(dataset.as_uri())

    assert loaded[0].dataset_version == "async_v1"


def test_file_url_directory_loads_manifest_and_provenance(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.yaml").write_text(
        "dataset_version: file_directory_v1\n"
        "source: file URL fixture\n"
        "files:\n  - cases.yaml\n"
    )
    (dataset / "cases.yaml").write_text(
        "- id: file-directory-case\n  expected:\n    final_status: closed\n"
    )

    loaded = load_cases(dataset.as_uri())

    assert loaded[0].dataset_version == "file_directory_v1"
    assert loaded[0].source == "file URL fixture"


def test_agent_run_defaults_to_not_skipped() -> None:
    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="test",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
    )
    assert run.skipped is False
    assert run.skip_reason is None

    skipped_run = AgentRun(
        run_id="run-2",
        case_id="case-2",
        adapter="test",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
        skipped=True,
        skip_reason="adapter does not support fault injection",
    )
    assert skipped_run.skipped is True
    assert skipped_run.skip_reason == "adapter does not support fault injection"
