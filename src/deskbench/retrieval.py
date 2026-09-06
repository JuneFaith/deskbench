"""RAG and hybrid retrieval evaluation pipeline for Deskbench."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any

import httpx
import yaml

from deskbench.adapters.base import RunHandle
from deskbench.adapters.tix_http import TixHttpAdapter
from deskbench.adapters.tix_retrieval import (
    RetrievalClient,
    TixHttpRetrievalClient,
    TixLocalHybridRetrievalClient,
    TixRetrievalAdapter,
)
from deskbench.reporting.json_report import ReportPaths
from deskbench.scorers.retrieval import (
    RetrievalExample,
    RetrievalResult,
    RetrievalScore,
    _metrics,
    score_retrieval,
)


def load_queries(path: str | Path) -> list[dict[str, Any]]:
    """Load query dataset from YAML or JSON file."""
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() == ".json":
        data = json.loads(content)
    else:
        data = yaml.safe_load(content)

    if isinstance(data, dict) and "queries" in data:
        items = data["queries"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"invalid queries dataset format in {file_path}")

    if not isinstance(items, list):
        raise ValueError(f"expected a list of queries in {file_path}")
    return items


async def _resolve_client(
    source: str,
    *,
    base_url: str | None = None,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    config_path: str | Path | None = None,
    client: httpx.AsyncClient | None = None,
    shared_token: str | None = None,
) -> tuple[RetrievalClient, str | None]:
    """Resolve and authenticate a retrieval client based on configuration."""
    url = (
        base_url
        or os.environ.get("DESKBENCH_TIX_URL")
        or os.environ.get("SERVICEDESKBENCH_TIX_URL")
    )
    tok = (
        token
        or shared_token
        or os.environ.get("DESKBENCH_TIX_TOKEN")
        or os.environ.get("SERVICEDESKBENCH_TIX_TOKEN")
    )
    usr = (
        username
        or os.environ.get("DESKBENCH_TIX_USERNAME")
        or os.environ.get("SERVICEDESKBENCH_TIX_USERNAME")
    )
    pwd = (
        password
        or os.environ.get("DESKBENCH_TIX_PASSWORD")
        or os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD")
    )
    cfg = (
        config_path
        or os.environ.get("DESKBENCH_TIX_CONFIG")
        or os.environ.get("SERVICEDESKBENCH_TIX_CONFIG")
    )

    if url:
        if not tok and usr and pwd:
            http_adapter = TixHttpAdapter(
                url,
                username=usr,
                password=pwd,
                client=client,
            )
            tok = await http_adapter.login()
            await http_adapter.cleanup(RunHandle(run_id="init", case_id="init"))
        http_client = TixHttpRetrievalClient(
            url,
            token=tok,
            source=source,
            client=client,
        )
        return http_client, tok

    if cfg and Path(cfg).is_file():
        return TixLocalHybridRetrievalClient(cfg, source=source), None

    raise ValueError("tix URL or config is required for retrieval evaluation")


def _render_markdown(
    run_id: str,
    source: str,
    case_count: int,
    passed_count: int,
    p95_latency_ms: float,
    overall_recall_at_5: float,
    overall_mrr: float,
    kb_score: RetrievalScore | None,
    ticket_score: RetrievalScore | None,
) -> str:
    """Render structured Markdown report with metrics table and topic breakdown."""
    lines: list[str] = [
        "# Deskbench Retrieval Evaluation Report",
        "",
        f"- **Run ID**: `{run_id}`",
        f"- **Source**: `{source}`",
        f"- **Cases**: {passed_count}/{case_count} passed",
        f"- **P95 Latency**: {p95_latency_ms:.2f} ms",
        f"- **Recall@5**: {overall_recall_at_5:.4f}",
        f"- **MRR**: {overall_mrr:.4f}",
        "- **Completion Rate**: 100.0%",
        "",
        "## Overall Metrics",
        "",
    ]

    if source == "both":
        lines.extend(
            [
                "| Metric | Overall | Knowledge Base (KB) | Tickets |",
                "| :--- | :--- | :--- | :--- |",
                f"| Recall@1 | {_avg(kb_score, ticket_score, 'recall_at_1'):.4f} | {_val(kb_score, 'recall_at_1')} | {_val(ticket_score, 'recall_at_1')} |",
                f"| Recall@3 | {_avg(kb_score, ticket_score, 'recall_at_3'):.4f} | {_val(kb_score, 'recall_at_3')} | {_val(ticket_score, 'recall_at_3')} |",
                f"| Recall@5 | {overall_recall_at_5:.4f} | {_val(kb_score, 'recall_at_5')} | {_val(ticket_score, 'recall_at_5')} |",
                f"| Precision@5 | {_avg(kb_score, ticket_score, 'precision_at_5'):.4f} | {_val(kb_score, 'precision_at_5')} | {_val(ticket_score, 'precision_at_5')} |",
                f"| MRR | {overall_mrr:.4f} | {_val(kb_score, 'mrr')} | {_val(ticket_score, 'mrr')} |",
                f"| NDCG@5 | {_avg(kb_score, ticket_score, 'ndcg_at_5'):.4f} | {_val(kb_score, 'ndcg_at_5')} | {_val(ticket_score, 'ndcg_at_5')} |",
                f"| Negative Leakage | {_avg(kb_score, ticket_score, 'negative_leakage'):.4f} | {_val(kb_score, 'negative_leakage')} | {_val(ticket_score, 'negative_leakage')} |",
                f"| Passed | {str(bool(kb_score and kb_score.passed and ticket_score and ticket_score.passed))} | {str(bool(kb_score and kb_score.passed))} | {str(bool(ticket_score and ticket_score.passed))} |",
            ]
        )
    elif source == "kb":
        lines.extend(
            [
                "| Metric | Knowledge Base (KB) |",
                "| :--- | :--- |",
                f"| Recall@1 | {_val(kb_score, 'recall_at_1')} |",
                f"| Recall@3 | {_val(kb_score, 'recall_at_3')} |",
                f"| Recall@5 | {_val(kb_score, 'recall_at_5')} |",
                f"| Precision@5 | {_val(kb_score, 'precision_at_5')} |",
                f"| MRR | {_val(kb_score, 'mrr')} |",
                f"| NDCG@5 | {_val(kb_score, 'ndcg_at_5')} |",
                f"| Negative Leakage | {_val(kb_score, 'negative_leakage')} |",
                f"| Passed | {str(bool(kb_score and kb_score.passed))} |",
            ]
        )
    else:
        lines.extend(
            [
                "| Metric | Tickets |",
                "| :--- | :--- |",
                f"| Recall@1 | {_val(ticket_score, 'recall_at_1')} |",
                f"| Recall@3 | {_val(ticket_score, 'recall_at_3')} |",
                f"| Recall@5 | {_val(ticket_score, 'recall_at_5')} |",
                f"| Precision@5 | {_val(ticket_score, 'precision_at_5')} |",
                f"| MRR | {_val(ticket_score, 'mrr')} |",
                f"| NDCG@5 | {_val(ticket_score, 'ndcg_at_5')} |",
                f"| Negative Leakage | {_val(ticket_score, 'negative_leakage')} |",
                f"| Passed | {str(bool(ticket_score and ticket_score.passed))} |",
            ]
        )

    lines.append("")
    lines.append("## Topic Breakdown")
    lines.append("")

    if kb_score and kb_score.topic_breakdown:
        lines.append("### Knowledge Base (KB)")
        lines.append("")
        lines.append("| Topic | Count | Recall@3 |")
        lines.append("| :--- | :--- | :--- |")
        for topic in sorted(kb_score.topic_breakdown):
            stats = kb_score.topic_breakdown[topic]
            lines.append(
                f"| {topic} | {int(stats.get('count', 0))} | {stats.get('recall_at_3', 0.0):.4f} |"
            )
        lines.append("")

    if ticket_score and ticket_score.topic_breakdown:
        lines.append("### Tickets")
        lines.append("")
        lines.append("| Topic | Count | Recall@3 |")
        lines.append("| :--- | :--- | :--- |")
        for topic in sorted(ticket_score.topic_breakdown):
            stats = ticket_score.topic_breakdown[topic]
            lines.append(
                f"| {topic} | {int(stats.get('count', 0))} | {stats.get('recall_at_3', 0.0):.4f} |"
            )
        lines.append("")

    return "\n".join(lines)


def _avg(s1: RetrievalScore | None, s2: RetrievalScore | None, field: str) -> float:
    vals: list[float] = []
    if s1 is not None:
        vals.append(getattr(s1, field))
    if s2 is not None:
        vals.append(getattr(s2, field))
    return sum(vals) / len(vals) if vals else 0.0


def _val(score: RetrievalScore | None, field: str) -> str:
    if score is None:
        return "-"
    val = getattr(score, field)
    if isinstance(val, float):
        return f"{val:.4f}"
    return str(val)


async def run_retrieval_evaluation(
    queries_path: str | Path,
    output_path: str | Path,
    source: str = "both",
    *,
    base_url: str | None = None,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    config_path: str | Path | None = None,
    min_score: float = 0.0,
    candidate_length: int = 5,
    kb_client: RetrievalClient | None = None,
    ticket_client: RetrievalClient | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ReportPaths:
    """Execute and score retrieval evaluation across queries dataset."""
    if source not in ("kb", "ticket", "both"):
        raise ValueError(f"invalid retrieval source: {source!r}")

    queries = load_queries(queries_path)
    run_timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S.%fZ")
    report_root = Path(output_path) / run_timestamp
    report_root.mkdir(parents=True, exist_ok=False)
    paths = ReportPaths(report_root)

    resolved_kb_client: RetrievalClient | None = kb_client
    resolved_ticket_client: RetrievalClient | None = ticket_client
    owned_clients: list[Any] = []
    shared_token: str | None = None

    if source in ("kb", "both") and resolved_kb_client is None:
        resolved_kb_client, shared_token = await _resolve_client(
            "kb",
            base_url=base_url,
            token=token,
            username=username,
            password=password,
            config_path=config_path,
            client=http_client,
            shared_token=shared_token,
        )
        owned_clients.append(resolved_kb_client)

    if source in ("ticket", "both") and resolved_ticket_client is None:
        resolved_ticket_client, shared_token = await _resolve_client(
            "ticket",
            base_url=base_url,
            token=token,
            username=username,
            password=password,
            config_path=config_path,
            client=http_client,
            shared_token=shared_token,
        )
        owned_clients.append(resolved_ticket_client)

    kb_adapter = (
        TixRetrievalAdapter(
            resolved_kb_client,
            min_score=min_score,
            candidate_length=candidate_length,
        )
        if resolved_kb_client
        else None
    )

    ticket_adapter = (
        TixRetrievalAdapter(
            resolved_ticket_client,
            min_score=min_score,
            candidate_length=candidate_length,
        )
        if resolved_ticket_client
        else None
    )

    all_durations: list[float] = []
    kb_examples: list[RetrievalExample] = []
    kb_results: list[RetrievalResult] = []
    ticket_examples: list[RetrievalExample] = []
    ticket_results: list[RetrievalResult] = []
    query_cases: list[dict[str, Any]] = []

    try:
        for idx, q in enumerate(queries):
            qid = str(q.get("id", f"query-{idx + 1}"))
            text = str(q.get("text", ""))
            theme = str(q.get("theme") or q.get("topic") or "unknown")

            expected_kb = list(q.get("expected_kb_articles", []))
            negative_kb = list(q.get("negative_kb_articles", []))
            expected_tickets = list(q.get("expected_tickets", []))
            negative_tickets = list(q.get("negative_tickets", []))

            case_record: dict[str, Any] = {
                "query_id": qid,
                "text": text,
                "theme": theme,
                "duration_ms": 0.0,
                "passed": True,
            }

            query_duration = 0.0

            # Execute KB retrieval
            if kb_adapter is not None:
                t0 = time.perf_counter()
                kb_res = await kb_adapter.search(qid, text)
                dur = (time.perf_counter() - t0) * 1000.0
                all_durations.append(dur)
                query_duration += dur

                kb_rec: dict[str, Any] = {
                    "document_ids": kb_res.document_ids,
                    "scores": kb_res.scores,
                    "passed": True,
                }

                if expected_kb or negative_kb:
                    ex = RetrievalExample(
                        query_id=qid,
                        relevant_ids=set(expected_kb),
                        negative_ids=set(negative_kb),
                        topic=theme,
                    )
                    res_obj = RetrievalResult(
                        query_id=qid,
                        document_ids=kb_res.document_ids,
                    )
                    kb_examples.append(ex)
                    kb_results.append(res_obj)
                    m = _metrics(ex, res_obj)
                    kb_rec["metrics"] = m
                    kb_passed = (m["negative_leakage"] == 0.0) and (
                        m["recall_at_5"] > 0.0 if expected_kb else True
                    )
                    kb_rec["passed"] = kb_passed
                    if not kb_passed:
                        case_record["passed"] = False

                case_record["kb"] = kb_rec

            # Execute Ticket retrieval
            if ticket_adapter is not None:
                t0 = time.perf_counter()
                tkt_res = await ticket_adapter.search(qid, text)
                dur = (time.perf_counter() - t0) * 1000.0
                all_durations.append(dur)
                query_duration += dur

                tkt_rec: dict[str, Any] = {
                    "document_ids": tkt_res.document_ids,
                    "scores": tkt_res.scores,
                    "passed": True,
                }

                if expected_tickets or negative_tickets:
                    ex = RetrievalExample(
                        query_id=qid,
                        relevant_ids=set(expected_tickets),
                        negative_ids=set(negative_tickets),
                        topic=theme,
                    )
                    res_obj = RetrievalResult(
                        query_id=qid,
                        document_ids=tkt_res.document_ids,
                    )
                    ticket_examples.append(ex)
                    ticket_results.append(res_obj)
                    m = _metrics(ex, res_obj)
                    tkt_rec["metrics"] = m
                    tkt_passed = (m["negative_leakage"] == 0.0) and (
                        m["recall_at_5"] > 0.0 if expected_tickets else True
                    )
                    tkt_rec["passed"] = tkt_passed
                    if not tkt_passed:
                        case_record["passed"] = False

                case_record["ticket"] = tkt_rec

            case_record["duration_ms"] = query_duration
            query_cases.append(case_record)
    finally:
        for oc in owned_clients:
            if hasattr(oc, "close"):
                await oc.close()

    kb_score = score_retrieval(kb_examples, kb_results) if kb_examples else None
    ticket_score = (
        score_retrieval(ticket_examples, ticket_results) if ticket_examples else None
    )

    if source == "both":
        if kb_score and ticket_score:
            overall_recall_at_5 = (
                kb_score.recall_at_5 + ticket_score.recall_at_5
            ) / 2.0
            overall_mrr = (kb_score.mrr + ticket_score.mrr) / 2.0
        elif kb_score:
            overall_recall_at_5 = kb_score.recall_at_5
            overall_mrr = kb_score.mrr
        elif ticket_score:
            overall_recall_at_5 = ticket_score.recall_at_5
            overall_mrr = ticket_score.mrr
        else:
            overall_recall_at_5 = 0.0
            overall_mrr = 0.0
    elif source == "kb":
        overall_recall_at_5 = kb_score.recall_at_5 if kb_score else 0.0
        overall_mrr = kb_score.mrr if kb_score else 0.0
    else:
        overall_recall_at_5 = ticket_score.recall_at_5 if ticket_score else 0.0
        overall_mrr = ticket_score.mrr if ticket_score else 0.0

    all_durations.sort()
    p95_latency_ms = (
        all_durations[max(0, ceil(len(all_durations) * 0.95) - 1)]
        if all_durations
        else 0.0
    )

    case_count = len(queries)
    passed_count = sum(1 for c in query_cases if c.get("passed", False))

    summary_data = {
        "run_id": run_timestamp,
        "timestamp": run_timestamp,
        "source": source,
        "approval_bypass_rate": 0.0,
        "cross_ticket_resume_rate": 0.0,
        "degraded_false_success_rate": 0.0,
        "illegal_transition_rate": 0.0,
        "forbidden_tool_rate": 0.0,
        "recall_at_5": overall_recall_at_5,
        "mrr": overall_mrr,
        "completion_rate": 1.0,
        "p95_latency_ms": p95_latency_ms,
        "mean_tool_calls": 0.0,
        "tool_call_growth_explanation": None,
        "case_count": case_count,
        "passed_count": passed_count,
        "kb_metrics": kb_score.model_dump(mode="json") if kb_score else None,
        "ticket_metrics": ticket_score.model_dump(mode="json")
        if ticket_score
        else None,
    }

    paths.summary.write_text(
        json.dumps(summary_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.cases.write_text(
        "".join(json.dumps(c, sort_keys=True) + "\n" for c in query_cases),
        encoding="utf-8",
    )
    paths.markdown.write_text(
        _render_markdown(
            run_id=run_timestamp,
            source=source,
            case_count=case_count,
            passed_count=passed_count,
            p95_latency_ms=p95_latency_ms,
            overall_recall_at_5=overall_recall_at_5,
            overall_mrr=overall_mrr,
            kb_score=kb_score,
            ticket_score=ticket_score,
        ),
        encoding="utf-8",
    )

    return paths
