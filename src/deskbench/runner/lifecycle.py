"""Dataset loading and Adapter lifecycle helpers."""

import importlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio
import yaml

from deskbench.contracts import Case, DatasetManifest


def load_manifest(path: str | Path) -> DatasetManifest:
    """Load a local manifest for a dataset directory or manifest file."""
    source = _manifest_source(path)
    if source.startswith("s3://"):
        raise RuntimeError(
            "s3:// datasets must be loaded with await load_manifest_async()"
        )
    payload = _read_yaml(source)
    if not isinstance(payload, dict):
        raise ValueError(f"manifest {source} must contain a YAML mapping")
    return DatasetManifest.model_validate(payload)


async def load_manifest_async(path: str | Path) -> DatasetManifest:
    """Load a manifest using asynchronous I/O for local or S3 URLs."""
    source = _manifest_source(path)
    payload = await _read_yaml_async(source)
    if not isinstance(payload, dict):
        raise ValueError(f"manifest {source} must contain a YAML mapping")
    return DatasetManifest.model_validate(payload)


def load_cases(path: str | Path) -> list[Case]:
    """Load benchmark cases from a YAML file, manifest, or dataset directory.

    A manifest's version and provenance are applied to cases that do not
    explicitly provide those fields. Local paths and ``file://`` URLs are
    supported synchronously; use :func:`load_cases_async` for ``s3://`` URLs.
    """
    source = str(path)
    if source.startswith("s3://"):
        raise RuntimeError(
            "s3:// datasets must be loaded with await load_cases_async()"
        )
    manifest_source = _manifest_source(source)
    if _is_manifest(source) or _is_directory(source):
        manifest = load_manifest(manifest_source)
        cases: list[Case] = []
        for relative_file in manifest.files:
            case_source = _join_source(manifest_source, relative_file)
            cases.extend(_load_case_file(case_source, manifest))
        return cases
    return _load_case_file(source, None)


async def load_cases_async(path: str | Path) -> list[Case]:
    """Load benchmark cases without blocking for local or S3 sources."""
    source = str(path)
    manifest_source = _manifest_source(source)
    if _is_manifest(source) or _is_directory(source) or _is_s3_prefix(source):
        manifest = await load_manifest_async(manifest_source)
        cases: list[Case] = []
        for relative_file in manifest.files:
            case_source = _join_source(manifest_source, relative_file)
            cases.extend(await _load_case_file_async(case_source, manifest))
        return cases
    return await _load_case_file_async(source, None)


def _load_case_file(source: str, manifest: DatasetManifest | None) -> list[Case]:
    payload = _read_yaml(source)
    if not isinstance(payload, list):
        raise ValueError(f"dataset {source} must contain a YAML list")
    cases: list[Case] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"dataset {source} contains a non-mapping case")
        data = dict(item)
        if manifest is not None:
            data.setdefault("dataset_version", manifest.dataset_version)
            data.setdefault("source", manifest.source)
            data.setdefault("annotation_notes", manifest.annotation_notes)
        cases.append(Case.model_validate(data))
    return cases


def _manifest_source(path: str | Path) -> str:
    source = str(path)
    if source.startswith("s3://") and not _is_manifest(source):
        if source.endswith((".yaml", ".yml")):
            return source
        return source.rstrip("/") + "/manifest.yaml"
    if _is_directory(source):
        if source.startswith("file://"):
            return source.rstrip("/") + "/manifest.yaml"
        return str(Path(source) / "manifest.yaml")
    if source.endswith(("/manifest.yaml", "/manifest.yml")):
        return source
    if _is_manifest(source):
        return source
    return source


def _is_directory(source: str) -> bool:
    parsed = urlparse(source)
    if parsed.scheme == "file":
        return Path(parsed.path).is_dir()
    if parsed.scheme == "s3":
        return _is_s3_prefix(source)
    return Path(source).is_dir()


def _is_manifest(source: str) -> bool:
    return source.endswith(("manifest.yaml", "manifest.yml"))


def _is_s3_prefix(source: str) -> bool:
    """Identify an S3 dataset prefix rather than an individual YAML object."""
    return source.startswith("s3://") and not source.endswith((".yaml", ".yml"))


def _join_source(base: str, relative: str) -> str:
    parsed = urlparse(base)
    if parsed.scheme == "s3":
        prefix = base.rsplit("/", 1)[0]
        return f"{prefix}/{relative}"
    if parsed.scheme == "file":
        return str(Path(base.removeprefix("file://")).parent / relative)
    return str(Path(base).parent / relative)


def _read_yaml(source: str) -> Any:
    if source.startswith("file://"):
        source = source.removeprefix("file://")
    return yaml.safe_load(Path(source).read_text())


async def _load_case_file_async(
    source: str, manifest: DatasetManifest | None
) -> list[Case]:
    payload = await _read_yaml_async(source)
    if not isinstance(payload, list):
        raise ValueError(f"dataset {source} must contain a YAML list")
    cases: list[Case] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"dataset {source} contains a non-mapping case")
        data = dict(item)
        if manifest is not None:
            data.setdefault("dataset_version", manifest.dataset_version)
            data.setdefault("source", manifest.source)
            data.setdefault("annotation_notes", manifest.annotation_notes)
        cases.append(Case.model_validate(data))
    return cases


async def _read_yaml_async(source: str) -> Any:
    if source.startswith("s3://"):
        try:
            sniffio = importlib.import_module("sniffio")

            if sniffio.current_async_library() != "asyncio":
                raise RuntimeError(
                    "s3:// dataset loading requires the asyncio AnyIO backend"
                )
        except RuntimeError:
            raise
        except ImportError:
            pass
        try:
            fsspec = importlib.import_module("fsspec")
        except ImportError as error:
            raise RuntimeError(
                "s3:// dataset paths require the deskbench[remote] extra"
            ) from error
        try:
            filesystem, object_path = fsspec.core.url_to_fs(source, asynchronous=True)
            cat = getattr(filesystem, "_cat", None)
            if cat is None:
                raise RuntimeError(
                    "configured S3 filesystem lacks asynchronous _cat support"
                )
            contents = await cat(object_path)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(
                f"unable to read remote dataset {source}: {error}"
            ) from error
        return yaml.safe_load(contents)
    local_source = source.removeprefix("file://")
    contents = await anyio.Path(local_source).read_text()
    return yaml.safe_load(contents)
