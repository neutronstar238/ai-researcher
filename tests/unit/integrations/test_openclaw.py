import json
from pathlib import Path

from autoresearch.integrations import (
    channel_adapter_manifest_payload,
    channel_plugin_manifest_payload,
    get_openclaw_channel_plugin,
    iter_openclaw_channel_plugins,
    write_channel_adapter_manifest,
    write_openclaw_channel_manifest,
)


def test_openclaw_channel_registry_includes_official_messaging_plugins() -> None:
    plugins = {plugin.channel_id: plugin for plugin in iter_openclaw_channel_plugins()}

    assert plugins["feishu"].package_name == "@larksuite/openclaw-lark"
    assert plugins["openclaw-weixin"].package_name == "@tencent-weixin/openclaw-weixin"
    assert plugins["wecom"].package_name == "@wecom/wecom-openclaw-plugin"
    assert plugins["telegram"].install_route == "included in OpenClaw"
    assert plugins["discord"].package_name == "@openclaw/discord"
    assert plugins["slack"].package_name == "@openclaw/slack"
    assert plugins["whatsapp"].package_name == "@openclaw/whatsapp"
    assert plugins["msteams"].package_name == "@openclaw/msteams"
    assert plugins["qqbot"].package_name == "@openclaw/qqbot"
    assert plugins["signal"].install_route == "included in OpenClaw"
    assert plugins["zalo"].package_name == "@openclaw/zalo"


def test_openclaw_manifest_contains_runtime_approval_bridge(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "openclaw" / "channels.json"

    write_openclaw_channel_manifest(output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    channels = {channel["channel_id"]: channel for channel in payload["channels"]}
    assert payload["approval_bridge"]["runtime_command"] == (
        "airesearcher serve --permission-mode approve-dangerous"
    )
    assert payload["approval_bridge"]["approve_command"].startswith(
        "airesearcher runtime approve latest"
    )
    assert "npx -y @tencent-weixin/openclaw-weixin-cli install" in channels[
        "openclaw-weixin"
    ]["install_commands"]
    assert "npx -y @wecom/wecom-openclaw-cli install" in channels["wecom"][
        "install_commands"
    ]
    assert "openclaw plugins install @larksuite/openclaw-lark" in channels["feishu"][
        "install_commands"
    ]


def test_channel_adapter_manifest_is_neutral_ai_researcher_runbook(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "channels" / "adapters.json"

    write_channel_adapter_manifest(output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    channels = {channel["channel_id"]: channel for channel in payload["channels"]}
    assert "AI-Researcher does not install or execute third-party plugins" in (
        "\n".join(payload["security_notes"])
    )
    assert channels["feishu"]["upstream_role"] == "optional messaging adapter reference"
    assert channels["openclaw-weixin"]["package_name"] == "@tencent-weixin/openclaw-weixin"


def test_openclaw_channel_lookup_accepts_channel_or_plugin_id() -> None:
    assert get_openclaw_channel_plugin("feishu").plugin_id == "openclaw-lark"
    assert get_openclaw_channel_plugin("openclaw-lark").channel_id == "feishu"


def test_openclaw_manifest_payload_is_json_serialisable() -> None:
    payload = channel_plugin_manifest_payload()

    text = json.dumps(payload, sort_keys=True)

    assert "AI-Researcher" in text
    assert "copy" not in text.casefold()


def test_channel_adapter_manifest_payload_is_json_serialisable() -> None:
    payload = channel_adapter_manifest_payload()

    text = json.dumps(payload, sort_keys=True)

    assert "AI-Researcher" in text
    assert "runbook only" in text
