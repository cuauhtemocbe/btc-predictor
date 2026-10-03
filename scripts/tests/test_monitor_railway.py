"""Tests for scripts/hooks/monitor-railway.sh (issue #82).

The script is driven against a stub `railway` executable that serves canned
`railway service list` snapshots, one per call (the last one repeats).
"""

import os
import stat
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "hooks" / "monitor-railway.sh"

SERVICES = ["btc-predictor", "weekly-predictor", "daily", "fetch-price"]


def block(
    name: str, status: str, deployment_id: str, extra: tuple[str, ...] = ()
) -> str:
    """One service block, laid out like `railway service list` prints it."""
    lines = [name, f"    status:        {status}", "    repo:          owner/repo"]
    lines += [f"    {field}" for field in extra]
    lines += ["    region:        US East", f"    deployment ID: {deployment_id}"]
    lines += [f"    service ID:    sid-{name}", ""]
    return "\n".join(lines) + "\n"


def snapshot(
    status: str = "● Online", suffix: str = "a", statuses: dict | None = None
) -> str:
    """A full listing where each service has a different number of optional fields."""
    statuses = statuses or {}
    extras = {
        "btc-predictor": ("url:           https://btc.example.app",),
        "weekly-predictor": ("replicas:      0/1 running",),
        "daily": (
            "url:           https://daily.example.app",
            "replicas:      0/1 running",
        ),
        "fetch-price": (),
    }
    body = "\nServices in production\n\n"
    for name in SERVICES:
        body += block(
            name, statuses.get(name, status), f"{name}-{suffix}", extras[name]
        )
    body += (
        "Postgres (linked)\n"
        "    status:        ● Online\n"
        "    image:         postgres:18\n\n"
    )
    return body


@pytest.fixture
def railway_stub(tmp_path):
    """Install a stub `railway` on PATH.

    Returns a namespace with `load(*snapshots)` to queue listings and
    `environment`, the process environment to run the script with.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    railway = bin_dir / "railway"
    railway.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            state="{state}"
            case "$1 $2" in
                "whoami "*) echo "tester"; exit 0 ;;
                "service list")
                    n=$(cat "$state/calls" 2>/dev/null || echo 0)
                    echo $((n + 1)) > "$state/calls"
                    file="$state/snapshot_$n"
                    [[ -f "$file" ]] ||
                        file=$(ls "$state"/snapshot_* | sort -V | tail -1)
                    cat "$file"
                    ;;
                "status "*|"logs "*) ;;
            esac
            """
        )
    )
    railway.chmod(railway.stat().st_mode | stat.S_IEXEC)

    def load(*snapshots: str) -> None:
        for i, text in enumerate(snapshots):
            (state / f"snapshot_{i}").write_text(text)

    return SimpleNamespace(
        load=load,
        environment={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MONITOR_CHECK_INTERVAL": "1",
            "MONITOR_TIMEOUT_SECONDS": "6",
        },
    )


def run_monitor(environment: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def source_field(service: str, label: str, listing: str) -> str:
    """Call the script's `service_field` helper (the script is sourceable)."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{SCRIPT}"; service_field "$1" "$2" "$3"',
            "_",
            service,
            label,
            listing,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.unit
class TestDeploymentIdParsing:
    """Scenario: Deployment ID is parsed correctly regardless of optional fields."""

    @pytest.mark.parametrize("service", SERVICES)
    def test_extracts_the_deployment_id_of_every_service(self, service):
        assert source_field(service, "deployment ID", snapshot()) == f"{service}-a"

    def test_does_not_leak_fields_from_a_neighbouring_service(self):
        # fetch-price has no optional lines; the next block must not be read
        listing = snapshot(suffix="x")

        assert source_field("fetch-price", "deployment ID", listing) == "fetch-price-x"

    def test_status_is_read_from_the_same_block(self):
        listing = snapshot(statuses={"daily": "● Building"})

        assert source_field("daily", "status", listing) == "● Building"
        assert source_field("btc-predictor", "status", listing) == "● Online"

    def test_service_name_must_match_the_whole_line(self):
        # "daily" must not match a service called "daily-extra"
        listing = block("daily-extra", "● Online", "wrong-id") + block(
            "daily", "● Online", "right-id"
        )

        assert source_field("daily", "deployment ID", listing) == "right-id"

    def test_missing_service_yields_an_empty_value(self):
        assert source_field("no-such-service", "deployment ID", snapshot()) == ""

    def test_missing_field_yields_an_empty_value(self):
        assert source_field("daily", "no such label", snapshot()) == ""


@pytest.mark.integration
class TestMonitorExitBehaviour:
    def test_reports_success_well_before_the_timeout(self, railway_stub):
        # Initial snapshot, then a deploy in flight, then all online with new ids
        railway_stub.load(
            snapshot(suffix="old"),
            snapshot(status="● Building", suffix="new"),
            snapshot(suffix="new"),
        )

        result = run_monitor(railway_stub.environment)

        assert result.returncode == 0, result.stdout
        assert "All services deployed successfully" in result.stdout
        assert "timeout" not in result.stdout.lower()

    def test_reports_failure_on_a_genuine_timeout(self, railway_stub):
        # Deployment ids never change: nothing was ever redeployed
        railway_stub.load(snapshot(suffix="same"))

        result = run_monitor(railway_stub.environment)

        assert result.returncode == 1
        assert "Deployment timeout after 6s" in result.stdout
        assert "deployed successfully" not in result.stdout

    def test_still_building_at_the_deadline_is_a_timeout(self, railway_stub):
        railway_stub.load(
            snapshot(suffix="old"), snapshot(status="● Building", suffix="new")
        )

        result = run_monitor(railway_stub.environment)

        assert result.returncode == 1
        assert "Deployment timeout" in result.stdout

    def test_a_failed_deployment_fails_immediately(self, railway_stub):
        railway_stub.load(
            snapshot(suffix="old"),
            snapshot(suffix="new", statuses={"daily": "● Failed"}),
        )

        result = run_monitor(railway_stub.environment)

        assert result.returncode == 1
        assert "daily deployment failed" in result.stdout
        assert "deployed successfully" not in result.stdout

    def test_silent_flag_suppresses_output(self, railway_stub):
        railway_stub.load(snapshot(suffix="old"), snapshot(suffix="new"))

        result = run_monitor(railway_stub.environment, "--silent")

        assert result.returncode == 0
        assert result.stdout == ""

    def test_missing_cli_exits_with_code_2(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()

        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env={"PATH": str(empty)},
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
