"""Deskbench retrieval evaluation entry point."""

from __future__ import annotations

import sys

from deskbench.retrieval import run_retrieval_evaluation

__all__ = ["run_retrieval_evaluation"]


def main(argv: list[str] | None = None) -> int:
    """Run retrieval evaluation via Deskbench CLI entry point."""
    from deskbench.cli import main as cli_main

    args = argv if argv is not None else sys.argv[1:]
    return cli_main(["retrieval", *args])


if __name__ == "__main__":
    sys.exit(main())
