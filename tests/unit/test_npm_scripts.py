import json
from pathlib import Path


def test_npm_scripts_expose_guided_prelaunch_commands() -> None:
    package_json = Path("package.json")
    payload = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = payload["scripts"]

    assert scripts["setup"] == "node ./bin/airesearcher.mjs setup"
    assert scripts["channel:test"] == "node ./bin/airesearcher.mjs channels test"
    assert scripts["readiness"] == "node ./bin/airesearcher.mjs readiness"
    assert scripts["prelaunch"] == (
        "node ./bin/airesearcher.mjs readiness "
        "--push-inspiration --require-channel-config --require-channel-sent"
    )
