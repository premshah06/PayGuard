#!/usr/bin/env python3
"""
gen_architecture.py — auto-generates ARCHITECTURE.md.

Regenerates between marker comments:
  <!-- FILES_START -->  …  <!-- FILES_END -->
  <!-- STATUS_START --> … <!-- STATUS_END -->

Mermaid diagrams are preserved as-is (written once, never overwritten).
Run automatically by the pre-commit hook (scripts/install_hooks.sh).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCH_PATH = REPO_ROOT / "ARCHITECTURE.md"

IGNORE_DIRS = {
    "__pycache__", ".git", ".github", "node_modules", ".venv", "venv",
    "dist", "build", ".pytest_cache", "htmlcov", ".eggs",
}
IGNORE_FILES = {".DS_Store", "*.pyc", "*.pyo"}

COMPONENTS = [
    ("producer/generator.py",  "Synthetic transaction generator"),
    ("consumer/features.py",   "Feature engineering pipeline"),
    ("consumer/consumer.py",   "Kafka → inference → PostgreSQL consumer"),
    ("ml/train.py",            "IsolationForest training + ONNX export"),
    ("inference/app.py",       "ONNX inference sidecar (FastAPI)"),
    ("api/main.py",            "REST API + WebSocket (FastAPI + asyncpg)"),
    ("frontend/src/App.jsx",   "React dashboard"),
    ("docker-compose.yml",     "Container orchestration"),
    ("Makefile",               "Developer workflow targets"),
    (".github/workflows/ci.yml", "CI pipeline"),
]

# ── Directory tree ────────────────────────────────────────────────

def _tree(root: Path, prefix: str = "", max_depth: int = 4, depth: int = 0) -> list[str]:
    if depth > max_depth:
        return []
    lines = []
    entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    entries = [e for e in entries if e.name not in IGNORE_DIRS and not e.name.startswith(".")]
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            lines.extend(_tree(entry, prefix + extension, max_depth, depth + 1))
    return lines


def build_file_tree() -> str:
    tree_lines = _tree(REPO_ROOT, max_depth=3)
    return "```\nPayGuard/\n" + "\n".join(tree_lines) + "\n```"


# ── Component status ──────────────────────────────────────────────

def build_status_table() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for path, description in COMPONENTS:
        full = REPO_ROOT / path
        exists = "✅ present" if full.exists() else "❌ missing"
        size = f"{full.stat().st_size:,} B" if full.exists() else "—"
        rows.append(f"| `{path}` | {description} | {exists} | {size} |")

    header = "| File | Component | Status | Size |"
    sep    = "|------|-----------|--------|------|"
    updated = f"\n_Last updated: {now}_\n"
    return "\n".join([header, sep, *rows]) + updated


# ── Marker replacement ────────────────────────────────────────────

def replace_between(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1:
        return text
    return text[: start + len(start_marker)] + "\n" + replacement + "\n" + text[end:]


# ── Main ──────────────────────────────────────────────────────────

def main() -> None:
    if not ARCH_PATH.exists():
        print(f"[gen_architecture] {ARCH_PATH} not found — skipping.")
        return

    content = ARCH_PATH.read_text(encoding="utf-8")
    content = replace_between(content, "<!-- FILES_START -->", "<!-- FILES_END -->", build_file_tree())
    content = replace_between(content, "<!-- STATUS_START -->", "<!-- STATUS_END -->", build_status_table())
    ARCH_PATH.write_text(content, encoding="utf-8")
    print(f"[gen_architecture] ARCHITECTURE.md updated ✓")


if __name__ == "__main__":
    main()
