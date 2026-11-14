"""
Guards for the Trivy accepted-risk file used by the `trivy-image` CI job
(meta-projects#92): the job must read `.trivyignore.yaml`, and every entry in it
must say why it is accepted and when it stops applying.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML ships no stubs; types-PyYAML is not a dependency

REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORE_FILE = ".trivyignore.yaml"


def _load_yaml(relative_path: str) -> dict[str, Any]:
    loaded = yaml.safe_load((REPO_ROOT / relative_path).read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_trivy_image_job_reads_the_repo_ignore_file() -> None:
    workflow = _load_yaml(".github/workflows/container-security.yml")

    env = workflow["jobs"]["trivy-image"]["env"]

    assert env["TRIVY_IGNOREFILE"] == IGNORE_FILE
    assert (REPO_ROOT / IGNORE_FILE).is_file()


def test_every_ignore_entry_has_a_statement_and_an_expiry() -> None:
    entries = _load_yaml(IGNORE_FILE)["vulnerabilities"]

    assert entries, "the ignore file should list at least one accepted finding"
    for entry in entries:
        assert entry.get("statement", "").strip(), f"{entry['id']}: statement missing"
        assert entry.get("expired_at"), f"{entry['id']}: expired_at missing"


def test_pip_vendored_entries_match_an_exact_purl() -> None:
    # Trivy reports packages vendored inside pip without a file path, so an
    # entry with neither paths nor purls would hide the CVE in every package.
    entries = _load_yaml(IGNORE_FILE)["vulnerabilities"]

    for entry in entries:
        assert entry.get("paths") or entry.get("purls"), (
            f"{entry['id']}: entry must be scoped by paths or purls"
        )


@pytest.mark.parametrize(
    "dockerfile",
    [
        "Dockerfile",
        "Dockerfile.api",
        "Dockerfile.fetch",
        "Dockerfile.ml",
        "Dockerfile.backtest",
    ],
)
def test_production_dockerfiles_patch_zlib1g(dockerfile: str) -> None:
    # The base image still ships zlib1g 1:1.3.dfsg+really1.3.1-1+b1
    # (CVE-2026-76844, CVE-2026-85091); the fix is in debian-security only.
    text = (REPO_ROOT / dockerfile).read_text()

    assert "--only-upgrade zlib1g" in text
