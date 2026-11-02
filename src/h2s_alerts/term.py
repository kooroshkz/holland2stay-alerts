"""Tiny helpers for terminal output."""

from __future__ import annotations

import os
import sys


def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _wrap(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _color() else text


def bold(text: str) -> str:
    return _wrap("1", text)


def dim(text: str) -> str:
    return _wrap("2", text)


def ok(text: str) -> str:
    return f"{_wrap('32', '✓')} {text}"


def bad(text: str) -> str:
    return f"{_wrap('31', '✗')} {text}"


def warn(text: str) -> str:
    return f"{_wrap('33', '!')} {text}"


def ask(question: str, default: str = "") -> str:
    hint = f" {dim('[' + default + ']')}" if default else ""
    try:
        answer = input(f"{question}{hint} ").strip()
    except EOFError:
        answer = ""
    return answer or default


def yes(question: str, default: bool = True) -> bool:
    answer = ask(question, "Y/n" if default else "y/N").lower()
    if answer == "y/n":  # pressed enter
        return default
    return answer.startswith("y")


def table(rows: list[list[str]], right: set[int] | None = None) -> str:
    if not rows:
        return ""
    right = right or set()
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for r in rows:
        cells = [c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths, strict=True))]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)
