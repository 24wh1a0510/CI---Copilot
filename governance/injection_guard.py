"""Injection guard — protects the pipeline from prompt injection and memory poisoning."""
from __future__ import annotations

import re

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    r"ignore (previous|all|above) instructions",
    r"you are now",
    r"disregard (your|all|previous)",
    r"forget (everything|all|your instructions)",
    r"new system prompt",
    r"override (your|the) (instructions|prompt|role)",
    r"act as (if|a|an)",
    r"pretend (you are|to be)",
    r"jailbreak",
    r"DAN mode",
    r"<\|im_start\|>",
    r"<\|endoftext\|>",
    r"\[INST\]",
    r"###\s*(Instruction|Human|System):",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]

# Patterns that could poison memory with false data
_MEMORY_POISON_PATTERNS = [
    r"store (false|fake|invented|made.up) (data|event|information)",
    r"pretend .+ acquired",
    r"make up .+ event",
    r"invent .+ competitor",
    r"hallucinate .+ memory",
]
_MEMORY_COMPILED = [re.compile(p, re.IGNORECASE) for p in _MEMORY_POISON_PATTERNS]

# Characters suspicious in competitor names
_COMPETITOR_NAME_DANGEROUS = re.compile(r"[<>{}\[\]\\;$|&`'\"]")


def is_injection(text: str) -> bool:
    """Return True if text contains a prompt injection pattern."""
    for pattern in _COMPILED:
        if pattern.search(text):
            return True
    return False


def memory_injection_guard(query: str) -> bool:
    """Return True (SAFE) if the query is safe to pass to the memory store.
    Return False if memory poisoning is detected."""
    for pattern in _MEMORY_COMPILED:
        if pattern.search(query):
            return False
    if is_injection(query):
        return False
    return True


def validate_competitor_name(name: str) -> bool:
    """Validate that a competitor name looks like a real company name, not an injection."""
    if not name or not name.strip():
        return False
    if len(name) > 200:
        return False
    if _COMPETITOR_NAME_DANGEROUS.search(name):
        return False
    if is_injection(name):
        return False
    return True


def sanitize_topic(topic: str) -> str:
    """Sanitize a research topic by removing dangerous characters."""
    # Remove control characters
    topic = re.sub(r"[\x00-\x1f\x7f]", "", topic)
    # Truncate
    return topic[:500]


def guard_research_input(topic: str, competitors: list[str]) -> tuple[bool, str]:
    """Full input validation for a research request.
    Returns (is_safe, reason)."""
    if is_injection(topic):
        return False, f"Prompt injection detected in topic: '{topic[:80]}'"
    if len(topic) > 500:
        return False, "Topic too long (max 500 characters)"
    for name in competitors:
        if not validate_competitor_name(name):
            return False, f"Invalid competitor name: '{name[:80]}'"
    return True, "OK"
