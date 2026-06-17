"""Restricted network policy for sandboxed experiment execution."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from autoresearch.observability import AuditEvent, AuditEventType, AuditLog

DEFAULT_ALLOWED_DOMAINS = (
    "api.openalex.org",
    "api.semanticscholar.org",
    "arxiv.org",
    "export.arxiv.org",
    "files.pythonhosted.org",
    "github.com",
    "pypi.org",
    "raw.githubusercontent.com",
    "semanticscholar.org",
)


@dataclass(frozen=True)
class NetworkDecision:
    """Decision returned by the restricted network policy."""

    allowed: bool
    domain: str
    reason: str | None = None


@dataclass(frozen=True)
class RestrictedNetworkPolicy:
    """Preflight network allowlist for sandboxed experiments.

    This MVP policy is enforceable when callers route network requests through
    `require_allowed()`. It does not install OS-level firewall or proxy rules.
    """

    allowed_domains: tuple[str, ...] = DEFAULT_ALLOWED_DOMAINS
    os_enforcement_supported: bool = False

    def check(self, url_or_domain: str) -> NetworkDecision:
        """Return whether a URL or domain is allowed."""

        domain = _extract_domain(url_or_domain)
        if not domain:
            return NetworkDecision(False, "", "missing network domain")
        if any(_domain_matches(domain, allowed) for allowed in self.allowed_domains):
            return NetworkDecision(True, domain)
        return NetworkDecision(False, domain, "domain is not in the sandbox allowlist")

    def require_allowed(
        self,
        url_or_domain: str,
        *,
        audit_log: AuditLog | None = None,
        actor: str = "sandbox",
        project_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> NetworkDecision:
        """Return the allow decision or raise and audit a blocked request."""

        decision = self.check(url_or_domain)
        if decision.allowed:
            return decision

        if audit_log is not None:
            audit_log.append(
                AuditEvent(
                    event_type=AuditEventType.SANDBOX_DENIAL,
                    actor=actor,
                    action="blocked network request",
                    resource=decision.domain or url_or_domain,
                    run_id=run_id,
                    project_id=project_id,
                    task_id=task_id,
                    approved=False,
                    metadata={
                        "url": url_or_domain,
                        "reason": decision.reason,
                        "allowed_domains": list(self.allowed_domains),
                        "enforcement": "preflight_only",
                        "os_enforcement_supported": self.os_enforcement_supported,
                    },
                )
            )

        msg = f"sandbox denied network access to {url_or_domain}: {decision.reason}"
        raise PermissionError(msg)


def default_network_policy() -> RestrictedNetworkPolicy:
    """Return the default MVP sandbox network policy."""

    return RestrictedNetworkPolicy()


def network_enforcement_note() -> str:
    """Document the MVP network enforcement boundary."""

    return (
        "MVP network policy is preflight/audit only; OS-level firewall or proxy "
        "enforcement is not implemented yet."
    )


def _extract_domain(url_or_domain: str) -> str:
    value = url_or_domain.strip().casefold()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").rstrip(".")


def _domain_matches(domain: str, allowed_domain: str) -> bool:
    allowed = allowed_domain.casefold().rstrip(".")
    return domain == allowed or domain.endswith(f".{allowed}")
