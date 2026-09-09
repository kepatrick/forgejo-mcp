"""Validate rendered deployment settings without starting containers or reading real secrets."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def docker_compose() -> str:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is not installed")
    result = subprocess.run(
        [docker, "compose", "version"], capture_output=True, check=False, timeout=30
    )
    if result.returncode != 0:
        pytest.skip("Docker Compose plugin is not installed")
    return docker


@pytest.mark.parametrize(
    ("overrides", "expected_proxies", "expected_tls"),
    [
        ({}, [], False),
        (
            {
                "FMCP_TRUSTED_PROXY_CIDRS": '["172.18.0.0/16", "2001:db8::/32"]',
                "FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS": "true",
            },
            ["172.18.0.0/16", "2001:db8::/32"],
            True,
        ),
    ],
)
def test_compose_security_settings_reach_container(
    docker_compose: str,
    tmp_path: Path,
    overrides: dict[str, str],
    expected_proxies: list[str],
    expected_tls: bool,
) -> None:
    # Isolate the test from checkout-local .env files and operator credentials.
    compose = tmp_path / "compose.yaml"
    shutil.copyfile(ROOT / "deploy/compose.yaml", compose)
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("FMCP_", "POSTGRES_", "COMPOSE_"))
    }
    env.update(
        FMCP_FORGEJO_ALLOWED_BASE_URLS='["https://forgejo.example.test"]',
        **overrides,
    )
    result = subprocess.run(
        [
            docker_compose,
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(compose),
            "config",
            "--format",
            "json",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    app = json.loads(result.stdout)["services"]["app"]
    settings = app["environment"]
    assert json.loads(settings["FMCP_TRUSTED_PROXY_CIDRS"]) == expected_proxies
    assert settings["FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS"].lower() == str(expected_tls).lower()
    assert "--no-proxy-headers" in " ".join(app["command"])
    assert settings["FMCP_DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert "FMCP_DATABASE_URL" not in settings
