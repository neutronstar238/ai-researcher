"""External integration manifests for AI-Researcher."""

from .cc_switch import (
    CCSwitchCodeAgentBackend,
    ccswitch_code_agent_manifest_payload,
    get_ccswitch_code_agent_backend,
    iter_ccswitch_code_agent_backends,
    write_ccswitch_code_agent_manifest,
)
from .openclaw import (
    OpenClawChannelPlugin,
    channel_plugin_manifest_payload,
    get_openclaw_channel_plugin,
    iter_openclaw_channel_plugins,
    write_openclaw_channel_manifest,
)
from .opencode import (
    OpenCodeCodeAgentBackend,
    get_opencode_code_agent_backend,
    iter_opencode_code_agent_backends,
    opencode_code_agent_manifest_payload,
    write_opencode_code_agent_manifest,
)

__all__ = [
    "CCSwitchCodeAgentBackend",
    "OpenClawChannelPlugin",
    "OpenCodeCodeAgentBackend",
    "ccswitch_code_agent_manifest_payload",
    "channel_plugin_manifest_payload",
    "get_ccswitch_code_agent_backend",
    "get_openclaw_channel_plugin",
    "get_opencode_code_agent_backend",
    "iter_ccswitch_code_agent_backends",
    "iter_openclaw_channel_plugins",
    "iter_opencode_code_agent_backends",
    "opencode_code_agent_manifest_payload",
    "write_ccswitch_code_agent_manifest",
    "write_openclaw_channel_manifest",
    "write_opencode_code_agent_manifest",
]
