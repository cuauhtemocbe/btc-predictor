# scripts/ — coverage gate

The global `--cov-fail-under=90` can hide a weak module, so each critical module also has its own
minimum in `[tool.coverage_thresholds]` of `pyproject.toml` (keys are repo-relative paths, values are
percent). `scripts/check_coverage_thresholds.py` reads the `coverage.xml` of the full run and exits
non-zero naming every module that is below its minimum or absent from the report (a worker no test
imports counts as missing). It runs in CI right after the coverage step and at the end of
`scripts/validate.sh` (pre-push), on the same `coverage.xml`, so the suite is never run twice.

```bash
# Same sequence as CI
docker compose exec api pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/coverage.xml
docker compose exec api python scripts/check_coverage_thresholds.py /tmp/coverage.xml
```

- **Setting a value:** measure the module, then take the largest multiple of 5 at least 2 points below it.
  Raise it after adding tests (same rule). Never lower it to pass: add the tests or explain the drop in the PR.
- **When it fails:** the `FAIL` rows and the last lines name the module, its coverage and its minimum.
  `not in the coverage report` means no test imports it or its path in the config is wrong (renames:
  update the key; `scripts/tests/test_check_coverage_thresholds.py` fails on orphan keys).
- **New critical module:** add its path to the table; `api/` paths in `coverage.xml` are mapped to `api-service/`.
