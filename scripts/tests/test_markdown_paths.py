"""Every repo path cited in a current markdown file exists (#180).

``docs/archive/``, ``specs/`` and ``CHANGELOG.md`` are history: they cite paths that
were later removed on purpose, so they are not checked.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
HISTORY_PREFIXES = ("docs/archive/", "specs/")
HISTORY_FILES = {"CHANGELOG.md"}
DOC_DIRECTORIES = ("docs", "shared", "workers", "scripts", "api-service")

# Paths that exist only at runtime (container, CI runner, generated output).
RUNTIME_PATHS = {
    "/app/entrypoint.sh",
    "/tmp/coverage.xml",
    "htmlcov/index.html",
    "mutation-output/mutation-report.txt",
    "mutation-output/session.sqlite",
    "coverage.xml",
    ".env",
}

BACKTICKED = re.compile(r"`([^`\n]+)`")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
PATH_SUFFIXES = (
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".sh",
    ".json",
    ".html",
    ".txt",
    ".cfg",
    ".ini",
    ".lock",
)


def tracked_markdown() -> list[str]:
    """Markdown files that describe the current state of the repository.

    The top level plus the directories that hold documentation. The test runs in
    the container, which has no ``git``, so it walks the tree instead of asking
    ``git ls-files``.
    """
    files = list(REPO_ROOT.glob("*.md"))
    for directory in DOC_DIRECTORIES:
        files.extend((REPO_ROOT / directory).rglob("*.md"))
    relative = (path.relative_to(REPO_ROOT).as_posix() for path in files)
    return sorted(
        path
        for path in relative
        if path not in HISTORY_FILES and not path.startswith(HISTORY_PREFIXES)
    )


def looks_like_repo_path(token: str) -> bool:
    """True for a token that names a file or directory of the repository."""
    if token.startswith(("-", "~", "http", "$")):
        return False
    if any(char in token for char in " <>*{}$|=()[],;\"'"):
        return False
    return "/" in token and (token.endswith("/") or token.endswith(PATH_SUFFIXES))


def cited_paths(markdown: str) -> set[str]:
    """Repo-relative paths cited in backticks, with any ``::symbol`` suffix removed."""
    paths = set()
    for token in BACKTICKED.findall(markdown):
        path = token.split("::")[0].rstrip("/")
        if looks_like_repo_path(path):
            paths.add(path)
    return paths


def link_targets(markdown: str) -> set[str]:
    """Relative link targets, without anchors; external links are skipped."""
    targets = set()
    for target in LINK_TARGET.findall(markdown):
        target = target.split("#")[0]
        if target and "://" not in target and not target.startswith("mailto:"):
            targets.add(target)
    return targets


def exists(path: str, markdown_file: str) -> bool:
    """Whether ``path`` exists from the repository root or from the markdown file."""
    if path in RUNTIME_PATHS:
        return True
    base = (REPO_ROOT / markdown_file).parent
    return (REPO_ROOT / path).exists() or (base / path).exists()


@pytest.mark.parametrize("markdown_file", tracked_markdown())
def test_cited_paths_exist(markdown_file: str) -> None:
    """Given a markdown file, every repo path it cites exists."""
    text = (REPO_ROOT / markdown_file).read_text()

    missing = sorted(
        {path for path in cited_paths(text) if not exists(path, markdown_file)}
        | {target for target in link_targets(text) if not exists(target, markdown_file)}
    )

    assert not missing, f"{markdown_file} cites paths that do not exist: {missing}"


def test_the_check_finds_a_missing_path() -> None:
    """Given a cited path that does not exist, the check reports it."""
    text = "See `shared/btc_shared/utils.py` and [a](docs/NOPE.md)."

    missing = {path for path in cited_paths(text) if not exists(path, "README.md")}

    assert missing == {"shared/btc_shared/utils.py"}
    assert {t for t in link_targets(text) if not exists(t, "README.md")} == {
        "docs/NOPE.md"
    }


def test_current_docs_are_checked_and_their_paths_found() -> None:
    """Given the repository docs, the README is in scope and its paths are extracted."""
    assert "README.md" in tracked_markdown()
    assert "docs/archive/specs/IMPLEMENTATION_HISTORY.md" not in tracked_markdown()
    readme = (REPO_ROOT / "README.md").read_text()
    assert "scripts/backtest.py" in cited_paths(readme)
