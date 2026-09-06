"""Command line interface for Deskbench."""

import argparse
import asyncio
import importlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

from deskbench.adapters.base import AgentAdapter
from deskbench.adapters.tix_http import TixHttpAdapter
from deskbench.evaluation import run_dataset
from deskbench.reporting import GatePolicy, evaluate_gate, read_summary
from deskbench.runner.lifecycle import load_cases_async


class _ArgumentParser(argparse.ArgumentParser):
    """Argument parser that raises a structured CLI error."""

    def error(self, message: str) -> NoReturn:
        """Raise a normal exception so ``main`` can emit an error envelope."""
        raise ValueError(f"invalid arguments: {message}")


def build_parser() -> argparse.ArgumentParser:
    """Build the Deskbench command parser."""
    parser = _ArgumentParser(prog="deskbench")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a dataset")
    run.add_argument("--dataset", required=True)
    run.add_argument("--adapter", choices=("graph", "http"), default="http")
    run.add_argument("--output", default="reports")
    run.add_argument("--json", action="store_true", dest="json_output")
    run.add_argument(
        "--pre-clean",
        action="store_true",
        help="clean environment and reset handler loads before running",
    )

    score = commands.add_parser("score", help="score an existing report")
    score.add_argument("--report", required=True)
    score.add_argument("--json", action="store_true", dest="json_output")

    gate = commands.add_parser("gate", help="evaluate regression gates")
    gate.add_argument("--report", required=True)
    gate.add_argument("--baseline")
    gate.add_argument("--json", action="store_true", dest="json_output")

    retrieval = commands.add_parser("retrieval", help="evaluate retrieval quality")
    retrieval.add_argument(
        "--queries",
        default="datasets/servicedesk_v1/rag_queries.yaml",
        help="path to queries dataset",
    )
    retrieval.add_argument(
        "--source",
        choices=("kb", "ticket", "both"),
        default="both",
        help="retrieval source to evaluate",
    )
    retrieval.add_argument(
        "--output",
        default="reports",
        help="output directory for reports",
    )
    retrieval.add_argument(
        "--json", action="store_true", dest="json_output", help="output in JSON format"
    )

    env = commands.add_parser(
        "env", help="environment diagnostics and cleanup"
    )
    env_sub = env.add_subparsers(dest="env_command", required=True)

    env_status = env_sub.add_parser("status", help="probe environment health and handler load")
    env_status.add_argument("--url", help="Tix base URL")
    env_status.add_argument("--json", action="store_true", dest="json_output")

    env_clean = env_sub.add_parser("clean", help="clean environment data and reset handler load")
    env_clean.add_argument("--url", help="Tix base URL")
    env_clean.add_argument(
        "--container", default="tix_pg_dev", help="Postgres container name"
    )
    env_clean.add_argument("--tix-path", help="Path to Tix repository")
    env_clean.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch the selected command."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit:
        raise
    except Exception as error:
        print(
            json.dumps(
                {"error": {"code": _error_code(error), "detail": str(error)}},
                sort_keys=True,
            )
        )
        return 2
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "score":
            report_path = Path(args.report)
            summary_path = (
                report_path / "summary.json" if report_path.is_dir() else report_path
            )
            summary = json.loads(summary_path.read_text())
            output = {
                "case_count": summary["case_count"],
                "passed_count": summary["passed_count"],
            }
            if "skipped_count" in summary:
                output["skipped_count"] = summary["skipped_count"]
            if args.json_output:
                print(json.dumps(output, sort_keys=True))
            else:
                skipped_suffix = (
                    f" ({output['skipped_count']} skipped)"
                    if output.get("skipped_count")
                    else ""
                )
                print(
                    f"scored {output['passed_count']}/{output['case_count']} cases{skipped_suffix}"
                )
            return 0
        if args.command == "retrieval":
            return _retrieval(args)
        if args.command == "env":
            return _env(args)
        current = read_summary(args.report)
        baseline = read_summary(args.baseline) if args.baseline else None
        result = evaluate_gate(current, baseline, GatePolicy())
        print(json.dumps(result.model_dump(), sort_keys=True))
        return 0 if result.passed else 1
    except Exception as error:
        print(
            json.dumps(
                {"error": {"code": _error_code(error), "detail": str(error)}},
                sort_keys=True,
            )
        )
        return 2


def _run(args: argparse.Namespace) -> int:
    return asyncio.run(_run_async(args))


async def _run_async(args: argparse.Namespace) -> int:
    cases = await load_cases_async(args.dataset)
    adapter: AgentAdapter
    if args.adapter == "graph":
        if getattr(args, "pre_clean", False):
            from deskbench.environment import clean_environment

            clean_res = await clean_environment()
            if not clean_res.get("cleaned"):
                raise RuntimeError(f"pre-clean failed: {clean_res.get('error')}")
        factory_path = os.environ.get("DESKBENCH_GRAPH_FACTORY") or os.environ.get(
            "SERVICEDESKBENCH_GRAPH_FACTORY"
        )
        if not factory_path:
            raise ValueError(
                "graph adapter requires DESKBENCH_GRAPH_FACTORY=module:factory"
            )
        from deskbench.adapters.tix_graph import TixGraphAdapter

        graph_adapter = TixGraphAdapter(_load_factory(factory_path))
        adapter = graph_adapter
    else:
        base_url = os.environ.get("DESKBENCH_TIX_URL") or os.environ.get(
            "SERVICEDESKBENCH_TIX_URL"
        )
        if not base_url:
            raise ValueError("tix URL is required for the HTTP adapter")
        token = (
            os.environ.get("DESKBENCH_TIX_TOKEN")
            or os.environ.get("SERVICEDESKBENCH_TIX_TOKEN")
        )
        username = (
            os.environ.get("DESKBENCH_TIX_USERNAME")
            or os.environ.get("SERVICEDESKBENCH_TIX_USERNAME")
        )
        password = (
            os.environ.get("DESKBENCH_TIX_PASSWORD")
            or os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD")
        )

        from deskbench.environment import clean_environment, probe_environment

        if getattr(args, "pre_clean", False):
            clean_res = await clean_environment(
                base_url=base_url,
                token=token,
                username=username,
                password=password,
            )
            if not clean_res.get("cleaned"):
                raise RuntimeError(f"pre-clean failed: {clean_res.get('error')}")

        status = await probe_environment(
            base_url=base_url,
            token=token,
            username=username,
            password=password,
        )
        if status.saturated_handlers:
            names = ", ".join(
                f"{h.name} ({h.current_load}/{h.max_load})"
                for h in status.saturated_handlers
            )
            warning_msg = (
                f"warning: {len(status.saturated_handlers)} handler(s) "
                f"are saturated: {names}"
            )
            if getattr(args, "json_output", False):
                print(warning_msg, file=sys.stderr)
            else:
                print(warning_msg)

        http_adapter = TixHttpAdapter(
            base_url,
            token,
            username=username,
            password=password,
        )
        adapter = http_adapter
    paths = await run_dataset(args.dataset, adapter, args.output)
    output: dict[str, Any] = {"case_count": len(cases), "report": str(paths.root)}
    if args.json_output:
        print(json.dumps(output, sort_keys=True))
    else:
        print(f"evaluated {len(cases)} cases; report: {paths.root}")
    return 0


def _env(args: argparse.Namespace) -> int:
    if args.env_command == "status":
        return asyncio.run(_env_status_async(args))
    if args.env_command == "clean":
        return asyncio.run(_env_clean_async(args))
    raise ValueError(f"invalid arguments: unknown env command {args.env_command}")


async def _env_status_async(args: argparse.Namespace) -> int:
    base_url = (
        getattr(args, "url", None)
        or os.environ.get("DESKBENCH_TIX_URL")
        or os.environ.get("SERVICEDESKBENCH_TIX_URL")
    )
    if not base_url:
        raise ValueError("tix URL is required for environment status")
    token = (
        os.environ.get("DESKBENCH_TIX_TOKEN")
        or os.environ.get("SERVICEDESKBENCH_TIX_TOKEN")
    )
    username = (
        os.environ.get("DESKBENCH_TIX_USERNAME")
        or os.environ.get("SERVICEDESKBENCH_TIX_USERNAME")
    )
    password = (
        os.environ.get("DESKBENCH_TIX_PASSWORD")
        or os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD")
    )

    from deskbench.environment import probe_environment

    status = await probe_environment(
        base_url=base_url,
        token=token,
        username=username,
        password=password,
    )

    if getattr(args, "json_output", False):
        print(json.dumps(status.model_dump(), sort_keys=True))
    else:
        health_label = "healthy" if status.healthy else f"unhealthy ({status.error})"
        print(f"Environment ({status.base_url}): {health_label}")
        if status.handlers:
            print(f"Handlers ({len(status.handlers)}):")
            for h in status.handlers:
                sat = " [SATURATED]" if h.is_saturated else ""
                print(
                    f"  - {h.name} ({h.id}): {h.current_load}/{h.max_load} "
                    f"active={h.active}{sat}"
                )
        if status.saturated_handlers:
            print(f"Warning: {len(status.saturated_handlers)} handler(s) saturated!")
    return 0 if status.healthy else 1


async def _env_clean_async(args: argparse.Namespace) -> int:
    base_url = (
        getattr(args, "url", None)
        or os.environ.get("DESKBENCH_TIX_URL")
        or os.environ.get("SERVICEDESKBENCH_TIX_URL")
    )
    token = (
        os.environ.get("DESKBENCH_TIX_TOKEN")
        or os.environ.get("SERVICEDESKBENCH_TIX_TOKEN")
    )
    username = (
        os.environ.get("DESKBENCH_TIX_USERNAME")
        or os.environ.get("SERVICEDESKBENCH_TIX_USERNAME")
    )
    password = (
        os.environ.get("DESKBENCH_TIX_PASSWORD")
        or os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD")
    )
    container = getattr(args, "container", "tix_pg_dev")
    tix_repo_path = getattr(args, "tix_path", None)

    from deskbench.environment import clean_environment

    result = await clean_environment(
        base_url=base_url,
        token=token,
        username=username,
        password=password,
        container_name=container,
        tix_repo_path=tix_repo_path,
    )

    if getattr(args, "json_output", False):
        print(json.dumps(result, sort_keys=True))
    else:
        if result.get("cleaned"):
            print(f"Environment cleaned successfully using {result.get('method')}.")
            if "status" in result and isinstance(result["status"], dict):
                st = result["status"]
                hl = (
                    "healthy"
                    if st.get("healthy")
                    else f"unhealthy ({st.get('error')})"
                )
                print(f"Environment ({st.get('base_url')}): {hl}")
        else:
            print(f"Environment clean failed: {result.get('error')}")
    return 0 if result.get("cleaned") else 1


def _retrieval(args: argparse.Namespace) -> int:
    return asyncio.run(_retrieval_async(args))


async def _retrieval_async(args: argparse.Namespace) -> int:
    from deskbench.retrieval import run_retrieval_evaluation

    paths = await run_retrieval_evaluation(
        queries_path=args.queries,
        output_path=args.output,
        source=args.source,
    )
    summary_data = json.loads(paths.summary.read_text(encoding="utf-8"))
    if args.json_output:
        output: dict[str, Any] = {
            "case_count": summary_data["case_count"],
            "passed_count": summary_data["passed_count"],
            "recall_at_5": summary_data["recall_at_5"],
            "mrr": summary_data["mrr"],
            "p95_latency_ms": summary_data["p95_latency_ms"],
            "completion_rate": summary_data["completion_rate"],
            "report": str(paths.root),
        }
        if summary_data.get("kb_metrics"):
            output["kb_metrics"] = summary_data["kb_metrics"]
        if summary_data.get("ticket_metrics"):
            output["ticket_metrics"] = summary_data["ticket_metrics"]
        print(json.dumps(output, sort_keys=True))
    else:
        print(f"Retrieval Evaluation Summary (source: {args.source}):")
        print(
            f"  Queries: {summary_data['passed_count']}/{summary_data['case_count']} passed"
        )
        print(f"  Recall@5: {summary_data['recall_at_5']:.4f}")
        print(f"  MRR: {summary_data['mrr']:.4f}")
        print(f"  P95 Latency: {summary_data['p95_latency_ms']:.2f} ms")
        print(f"  Report: {paths.root}")
    return 0


def _load_factory(path: str) -> Any:
    """Load a configured graph factory from ``module:attribute``."""
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("graph factory must use module:attribute syntax")
    factory = getattr(importlib.import_module(module_name), attribute)
    return cast(Any, factory)


def _error_code(error: Exception) -> str:
    return "missing_tix_url" if "tix URL" in str(error) else "evaluation_error"


if __name__ == "__main__":
    raise SystemExit(main())
