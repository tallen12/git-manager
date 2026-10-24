import json
from contextlib import AbstractAsyncContextManager, nullcontext
from pathlib import Path

import pytest

from git_manager.cli.main import build_app
from git_manager.config import CheckoutRepoConfig, ConfigService, YamlConfigFile
from git_manager.core import LocalTarget, Operations, Service, build_connector
from git_manager.core.unavailable import UnavailableBranches, UnavailableRuns
from git_manager.health import HealthReporter, HealthService
from tests.conftest import TEST_VERSION, run_cli
from tests.unit.cli.conftest import no_runtime


def test_show_and_validate_read_the_same_layers(
    reporter: HealthReporter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clone = tmp_path / "data" / "repo"
    clone.mkdir(parents=True)
    (clone / ".git-manager.yaml").write_text("defaults: {max_restarts: 6}\n", encoding="utf-8")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"repo:\n  url: u\n  trust_repo_config: true\n  data_dir: {tmp_path / 'data'}\n"
        "branches:\n  - {name: a, base: main}\n",
        encoding="utf-8",
    )
    environ = {"GM_BUDGET__DAILY_USD": "3"}

    def read_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ=environ, repo_config=CheckoutRepoConfig())

    def local(target: LocalTarget) -> AbstractAsyncContextManager[Operations]:
        reason = "not built in this test"
        return nullcontext(
            Service(
                health=HealthService(reporter=reporter),
                config=ConfigService(read_config(target.config)),
                branches=UnavailableBranches(reason),
                runs=UnavailableRuns(reason),
            )
        )

    app = build_app(
        open_runtime=no_runtime,
        read_config=read_config,
        connect=build_connector(local=local),
        version=TEST_VERSION,
    )
    monkeypatch.setenv("GM_TARGET__CONFIG", str(config_file))

    assert run_cli(app, ["config", "validate"]) == 0
    assert run_cli(app, ["config", "show"]) == 0

    out = capsys.readouterr().out
    shown = json.loads(out[out.index("{") :])
    assert shown["budget"]["daily_usd"] == 3
    assert shown["branches"][0]["max_restarts"] == 6
