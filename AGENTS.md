---
project_context:
  language: "Python" # Confirmed stack (Python 3.14 runtime available)
  # Hard token-free local validation command execution strings
  lint_command: "ruff check --fix" # Requires ruff on PATH (not yet installed)
  test_command: "pytest" # Requires pytest on PATH (not yet installed)
---

# Local Project Constraints
- This repository houses our active core development assets.
- Ensure all modules remain self-contained.
- Stack: Python 3.14; no package manifest (`pyproject.toml`/`requirements.txt`) or source modules exist yet.
- Firewall: Python-tailored `.gitignore` present at repository root (bytecode, virtualenvs, caches, research data).
- Validation: run the declared lint/test commands from the repository root; install `ruff` and `pytest` first if they are absent.
