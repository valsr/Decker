#!/usr/bin/env python3
"""Regenerate spell.dic for pylint's spell checker.

Workflow:
  1. AST-walk all Python files in src/, tests/, and .stubs/ to extract every
     import-path segment and class name  →  spell.types.dic  (auto-generated)
  2. Merge with spell.user.dic  (hand-maintained)
  3. Sort, deduplicate, write  →  spell.dic  (consumed by pylint)

Run via:  poe update-dictionary
"""

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SCAN_DIRS = ["src", "tests", ".stubs"]
_TYPES_DIC = _ROOT / "spell.types.dic"
_USER_DIC = _ROOT / "spell.user.dic"
_SPELL_DIC = _ROOT / "spell.dic"


def _words_from_file(path: Path) -> set[str]:
    """Return all import-path segments and class names found in one Python file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    words: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                words.update(alias.name.split("."))
                if alias.asname:
                    words.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                words.update(node.module.split("."))
            for alias in node.names:
                if alias.name != "*":
                    words.add(alias.name)
                if alias.asname:
                    words.add(alias.asname)
        elif isinstance(node, ast.ClassDef):
            words.add(node.name)
    return words


def _keep(word: str) -> bool:
    """True for words worth putting in a spell dictionary."""
    if len(word) <= 1:
        return False
    if re.fullmatch(r"__\w+__", word):  # dunder names
        return False
    if re.fullmatch(r"\d[\d_]*", word):  # pure numbers
        return False
    return True


def _load_lines(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def main() -> None:
    # --- Phase 1: collect from codebase ---
    type_words: set[str] = set()
    for dir_name in _SCAN_DIRS:
        scan_path = _ROOT / dir_name
        if not scan_path.exists():
            continue
        for py_file in scan_path.rglob("*.py"):
            type_words.update(_words_from_file(py_file))

    type_words = {w for w in type_words if _keep(w)}
    sorted_types = sorted(type_words)
    _TYPES_DIC.write_text("\n".join(sorted_types) + "\n", encoding="utf-8")
    print(f"spell.types.dic  {len(sorted_types):>5} entries")

    # --- Phase 2: merge with user dictionary ---
    user_words = _load_lines(_USER_DIC)
    combined = sorted(type_words | user_words)
    _SPELL_DIC.write_text("\n".join(combined) + "\n", encoding="utf-8")
    print(f"spell.user.dic   {len(user_words):>5} entries")
    print(f"spell.dic        {len(combined):>5} entries  (merged, sorted, deduped)")


if __name__ == "__main__":
    main()
