"""External integration manifests for AI-Researcher."""

from .openclaw import (
    OpenClawChannelPlugin,
    channel_plugin_manifest_payload,
    get_openclaw_channel_plugin,
    iter_openclaw_channel_plugins,
    write_openclaw_channel_manifest,
)

__all__ = [
    "OpenClawChannelPlugin",
    "channel_plugin_manifest_payload",
    "get_openclaw_channel_plugin",
    "iter_openclaw_channel_plugins",
    "write_openclaw_channel_manifest",
]
