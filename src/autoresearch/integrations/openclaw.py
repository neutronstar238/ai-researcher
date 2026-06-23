"""OpenClaw channel plugin registry for operator deployments."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class OpenClawChannelPlugin:
    """Repository-tracked metadata for an external OpenClaw channel plugin."""

    channel_id: str
    plugin_id: str
    label: str
    package_name: str | None
    source_url: str
    license: str
    origin: str
    install_route: str
    install_commands: tuple[str, ...]
    verify_commands: tuple[str, ...]
    notes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        data = asdict(self)
        for field in ("install_commands", "verify_commands", "notes"):
            data[field] = list(data[field])
        return data


OPENCLAW_CHANNEL_PLUGINS: tuple[OpenClawChannelPlugin, ...] = (
    OpenClawChannelPlugin(
        channel_id="feishu",
        plugin_id="openclaw-lark",
        label="Lark/Feishu",
        package_name="@larksuite/openclaw-lark",
        source_url="https://github.com/larksuite/openclaw-lark",
        license="MIT",
        origin="Official Lark/Feishu Open Platform plugin",
        install_route="npm via OpenClaw plugins",
        install_commands=(
            "openclaw plugins install @larksuite/openclaw-lark",
            "openclaw plugins enable openclaw-lark",
            "openclaw gateway restart",
        ),
        verify_commands=(
            "openclaw plugins inspect openclaw-lark --runtime --json",
            "openclaw channels status feishu",
        ),
        notes=(
            "Current package metadata requires Node.js >=22 and peer OpenClaw >=2026.5.4.",
            "Use the upstream usage guide for app ID, app secret, event subscription, and workspace permissions.",
            "Map incoming /approve messages to `airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json`.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="openclaw-weixin",
        plugin_id="openclaw-weixin",
        label="Weixin / WeChat",
        package_name="@tencent-weixin/openclaw-weixin",
        source_url="https://github.com/Tencent/openclaw-weixin",
        license="MIT",
        origin="Official Tencent Weixin OpenClaw plugin",
        install_route="quick installer or npm via OpenClaw plugins",
        install_commands=(
            "npx -y @tencent-weixin/openclaw-weixin-cli install",
            "openclaw plugins install @tencent-weixin/openclaw-weixin",
            "openclaw config set plugins.entries.openclaw-weixin.enabled true",
            "openclaw channels login --channel openclaw-weixin",
            "openclaw gateway restart",
        ),
        verify_commands=(
            "openclaw plugins inspect openclaw-weixin --runtime --json",
            "openclaw channels status openclaw-weixin",
        ),
        notes=(
            "Current package metadata requires Node.js >=22 and peer OpenClaw >=2026.3.22.",
            "The quick installer performs plugin setup and QR-code login flow when supported.",
            "Use the AI-Researcher approval queue for dangerous research-loop actions.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="wecom",
        plugin_id="wecom-openclaw-plugin",
        label="WeCom / Enterprise WeChat",
        package_name="@wecom/wecom-openclaw-plugin",
        source_url="https://github.com/WecomTeam/wecom-openclaw-plugin",
        license="MIT",
        origin="Official Tencent WeCom team plugin",
        install_route="quick installer or npm via OpenClaw plugins",
        install_commands=(
            "npx -y @wecom/wecom-openclaw-cli install",
            "openclaw plugins install @wecom/wecom-openclaw-plugin",
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=(
            "openclaw plugins inspect wecom-openclaw-plugin --runtime --json",
            "openclaw channels status wecom",
        ),
        notes=(
            "Current package metadata requires peer OpenClaw >=2026.3.28.",
            "Bot mode uses Bot ID and secret; Agent mode uses callback token and EncodingAESKey.",
            "Keep WeCom allowlists narrow for group chats and command authorization.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="telegram",
        plugin_id="telegram",
        label="Telegram",
        package_name="@openclaw/telegram",
        source_url="https://docs.openclaw.ai/plugins/reference/telegram",
        license="OpenClaw distribution",
        origin="OpenClaw official bundled channel plugin",
        install_route="included in OpenClaw",
        install_commands=(
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status telegram",),
        notes=(
            "OpenClaw docs list Telegram as included in OpenClaw.",
            "Store Telegram bot tokens in OpenClaw credentials or local environment, not in this repository.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="discord",
        plugin_id="discord",
        label="Discord",
        package_name="@openclaw/discord",
        source_url="https://docs.openclaw.ai/plugins/reference/discord",
        license="OpenClaw distribution",
        origin="OpenClaw official channel plugin",
        install_route="npm or ClawHub",
        install_commands=(
            "openclaw plugins install @openclaw/discord",
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status discord",),
        notes=(
            "Discord requires a bot token and Message Content Intent for normal chat handling.",
            "Prefer private test servers before exposing AI-Researcher to shared workspaces.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="slack",
        plugin_id="slack",
        label="Slack",
        package_name="@openclaw/slack",
        source_url="https://docs.openclaw.ai/plugins/reference/slack",
        license="OpenClaw distribution",
        origin="OpenClaw official channel plugin",
        install_route="npm or ClawHub",
        install_commands=(
            "openclaw plugins install @openclaw/slack",
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status slack",),
        notes=(
            "Use least-privilege Slack scopes and workspace allowlists.",
            "Route approval messages to the runtime approval queue before running dangerous actions.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="whatsapp",
        plugin_id="whatsapp",
        label="WhatsApp",
        package_name="@openclaw/whatsapp",
        source_url="https://docs.openclaw.ai/plugins/reference/whatsapp",
        license="OpenClaw distribution",
        origin="OpenClaw official channel plugin",
        install_route="ClawHub or npm",
        install_commands=(
            "openclaw plugins install clawhub:@openclaw/whatsapp",
            "openclaw channels login --channel whatsapp",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status whatsapp",),
        notes=(
            "WhatsApp setup is account-pairing based; keep credentials outside the repository.",
            "Use only for operator messaging until media and group policies are reviewed.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="msteams",
        plugin_id="msteams",
        label="Microsoft Teams",
        package_name="@openclaw/msteams",
        source_url="https://docs.openclaw.ai/plugins/reference/msteams",
        license="OpenClaw distribution",
        origin="OpenClaw official channel plugin",
        install_route="npm or ClawHub",
        install_commands=(
            "openclaw plugins install @openclaw/msteams",
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status msteams",),
        notes=(
            "Use tenant-scoped bot credentials and conservative command permissions.",
            "Treat Teams channels as production workspaces unless explicitly isolated.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="qqbot",
        plugin_id="qqbot",
        label="QQ Bot",
        package_name="@openclaw/qqbot",
        source_url="https://docs.openclaw.ai/plugins/reference/qqbot",
        license="OpenClaw distribution",
        origin="OpenClaw official channel plugin",
        install_route="npm or ClawHub",
        install_commands=(
            "openclaw plugins install @openclaw/qqbot",
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status qqbot",),
        notes=(
            "Use QQ Bot official API credentials and group allowlists.",
            "Review media permissions before enabling file or image handling.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="signal",
        plugin_id="signal",
        label="Signal",
        package_name="@openclaw/signal",
        source_url="https://docs.openclaw.ai/plugins/reference/signal",
        license="OpenClaw distribution",
        origin="OpenClaw official bundled channel plugin",
        install_route="included in OpenClaw",
        install_commands=(
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status signal",),
        notes=(
            "OpenClaw docs list Signal as included in OpenClaw.",
            "Keep device/session state in OpenClaw-managed storage, not this repository.",
        ),
    ),
    OpenClawChannelPlugin(
        channel_id="zalo",
        plugin_id="zalo",
        label="Zalo",
        package_name="@openclaw/zalo",
        source_url="https://docs.openclaw.ai/channels/zalo",
        license="OpenClaw distribution",
        origin="OpenClaw official bundled channel plugin",
        install_route="included in current OpenClaw releases; npm fallback",
        install_commands=(
            "openclaw plugins install @openclaw/zalo",
            "openclaw channels add",
            "openclaw gateway restart",
        ),
        verify_commands=("openclaw channels status zalo",),
        notes=(
            "Current OpenClaw docs describe Zalo as bundled in packaged releases.",
            "Use Zalo Bot Platform tokens and keep DM pairing enabled by default.",
        ),
    ),
)


def iter_openclaw_channel_plugins() -> tuple[OpenClawChannelPlugin, ...]:
    """Return all channel plugin entries in deterministic order."""

    return OPENCLAW_CHANNEL_PLUGINS


def get_openclaw_channel_plugin(channel_id: str) -> OpenClawChannelPlugin:
    """Return one plugin entry by channel or plugin ID."""

    normalized = channel_id.casefold()
    for plugin in OPENCLAW_CHANNEL_PLUGINS:
        if normalized in {plugin.channel_id.casefold(), plugin.plugin_id.casefold()}:
            return plugin
    msg = f"unknown OpenClaw channel plugin: {channel_id}"
    raise KeyError(msg)


def channel_plugin_manifest_payload() -> dict[str, object]:
    """Build the checked-in OpenClaw channel manifest payload."""

    return {
        "schema_version": 1,
        "generated_for": "AI-Researcher",
        "purpose": (
            "Reference install/runbook metadata for mounting official OpenClaw "
            "communication channels onto the AI-Researcher runtime."
        ),
        "approval_bridge": {
            "local_state": ".airesearcher/runtime-approvals.json",
            "approve_command": "airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json",
            "list_command": "airesearcher runtime list --state .airesearcher/runtime-approvals.json",
            "runtime_command": "airesearcher serve --permission-mode approve-dangerous",
        },
        "security_notes": [
            "This manifest records install commands; it does not vendor or execute third-party plugins.",
            "Install plugins only in an OpenClaw deployment after reviewing upstream licenses and permissions.",
            "Keep channel secrets in OpenClaw credentials, `.env`, or platform secret stores, never in git.",
            "Route dangerous actions through AI-Researcher runtime approval before execution.",
        ],
        "channels": [plugin.to_json_dict() for plugin in OPENCLAW_CHANNEL_PLUGINS],
    }


def channel_adapter_manifest_payload() -> dict[str, object]:
    """Build a neutral upstream messaging-adapter runbook payload."""

    payload = channel_plugin_manifest_payload()
    payload["purpose"] = (
        "Reference metadata for optional upstream messaging adapters that can bridge "
        "operator channels such as WeChat and Feishu into the AI-Researcher runtime."
    )
    payload["security_notes"] = [
        "This manifest is a runbook only; AI-Researcher does not install or execute third-party plugins.",
        "Review upstream licenses, permissions, and platform terms before installing any adapter elsewhere.",
        "Keep channel secrets in `.env` or platform secret stores, never in git.",
        "Route dangerous actions through AI-Researcher runtime approval before execution.",
    ]
    payload["channels"] = [
        {
            **plugin.to_json_dict(),
            "upstream_role": "optional messaging adapter reference",
        }
        for plugin in OPENCLAW_CHANNEL_PLUGINS
    ]
    return payload


def write_openclaw_channel_manifest(output_path: Path | str) -> Path:
    """Write the OpenClaw channel manifest to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(channel_plugin_manifest_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def write_channel_adapter_manifest(output_path: Path | str) -> Path:
    """Write the neutral messaging-adapter runbook manifest to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(channel_adapter_manifest_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
