"""Source trust scoring — generic, not per-industry.

Assigns a trust tier (high / medium / low) to every Source based on its domain,
TLD, and known low-trust signals. The result is stored in Source.trust_tier and
Source.trust_reason so the UI and governance layer can surface it.
"""
from __future__ import annotations

HIGH_TRUST_TLDS = {".gov", ".edu", ".ac.in", ".org"}

HIGH_TRUST_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "techcrunch.com",
    "ft.com",
    "wsj.com",
    "forbes.com",
    "crunchbase.com",
    "tracxn.com",
    "wikipedia.org",
}

LOW_TRUST_SIGNALS = {
    "blog.",
    "reddit.com",
    "random-",
    ".example",
    "medium.com",
}


def score_domain(domain: str) -> dict:
    """Return {"domain": domain, "tier": "high"|"medium"|"low", "reason": str}."""
    d = domain.lower().strip()

    # Strip leading "www."
    if d.startswith("www."):
        d = d[4:]

    # Check for known high-trust exact domains
    for hd in HIGH_TRUST_DOMAINS:
        if d == hd or d.endswith("." + hd):
            return {"domain": domain, "tier": "high", "reason": f"known trusted domain: {hd}"}

    # Check for high-trust TLDs
    for tld in HIGH_TRUST_TLDS:
        if d.endswith(tld):
            return {"domain": domain, "tier": "high", "reason": f"trusted TLD: {tld}"}

    # Check for low-trust signals
    for signal in LOW_TRUST_SIGNALS:
        if signal in d:
            return {"domain": domain, "tier": "low", "reason": f"low-trust signal: {signal}"}

    # Default
    return {"domain": domain, "tier": "medium", "reason": "no specific trust signal found"}


def annotate_sources(sources: list) -> list:
    """Add trust_tier and trust_reason to each Source in-place (returns same list)."""
    for src in sources:
        result = score_domain(getattr(src, "domain", "") or "")
        src.trust_tier = result["tier"]
        src.trust_reason = result["reason"]
    return sources
