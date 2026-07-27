# Contributing

Open an issue before a substantial change. Pull requests should explain the problem and approach, include focused tests and synthetic fixtures, update affected documentation and the changelog, and preserve the project's stated safety and privacy boundaries.

Run the complete local checks before submitting:

\`\`\`bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
python -m build
python -m pip_audit
\`\`\`

Do not contribute copyrighted comic pages, private collection or gaming data, credentials, generated filler, fabricated sources, or proprietary databases.
