"""Command line interface for Deskbench."""

import argparse
import asyncio
import importlib
import json
import os
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
        http_adapter = TixHttpAdapter(
            base_url,
            os.environ.get("DESKBENCH_TIX_TOKEN")
            or os.environ.get("SERVICEDESKBENCH_TIX_TOKEN"),
            username=os.environ.get("DESKBENCH_TIX_USERNAME")
            or os.environ.get("SERVICEDESKBENCH_TIX_USERNAME"),
            password=os.environ.get("DESKBENCH_TIX_PASSWORD")
            or os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD"),
        )
        adapter = http_adapter
    paths = await run_dataset(args.dataset, adapter, args.output)
    output: dict[str, Any] = {"case_count": len(cases), "report": str(paths.root)}
    if args.json_output:
        print(json.dumps(output, sort_keys=True))
    else:
        print(f"evaluated {len(cases)} cases; report: {paths.root}")
    return 0


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
