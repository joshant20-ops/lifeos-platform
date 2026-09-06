#!/usr/bin/env python3
"""Parse agent CLI output without mistaking prompt echoes for completion."""
from __future__ import annotations

import pathlib
import re
import sys

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_FRAME = " │┃║|┆┇┊┋"


def normalized_lines(text: str):
    clean = _ANSI.sub("", str(text)).replace("\r", "\n")
    for raw in clean.splitlines():
        line = raw.strip().strip(_FRAME).strip()
        if line:
            yield line


def declares_pass(text: str) -> bool:
    """Accept an explicit PASS result even when a TUI decorates the line."""
    return any(line == "RESULT=PASS" for line in normalized_lines(text))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 2
    try:
        text = pathlib.Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 2
    return 0 if declares_pass(text) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
