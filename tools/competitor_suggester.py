"""Competitor Suggester — extracts real company names from news headlines.

Strategy:
  1. Search DDG News for '{topic} company news' — news results have short, clean
     headlines that name actual companies (not listicle page titles).
  2. Extract capitalized proper-noun phrases from headlines using a tight regex.
  3. Count frequency — names that appear in 2+ headlines are real companies.
  4. Resolve each name to a domain via a quick DDG lookup.
  5. Return top 8, deduped by domain.

Never touches SearchBudget.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


# ── DDG helper ────────────────────────────────────────────────────────────────
def _get_ddgs():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        return DDGS


# ── Domain helpers ────────────────────────────────────────────────────────────
def _domain(url: str) -> str:
    try:
        n = urlparse(url).netloc.lower()
        return n[4:] if n.startswith("www.") else n
    except Exception:
        return ""


_SKIP = {
    "google.", "bing.", "yahoo.", "duckduckgo.", "reddit.", "quora.",
    "wikipedia.", "youtube.", "twitter.", "x.com", "facebook.", "instagram.",
    "linkedin.", "medium.", "substack.", "wordpress.", "blogspot.",
    "forbes.", "techcrunch.", "bloomberg.", "reuters.", "businessinsider.",
    "economictimes.", "livemint.", "moneycontrol.", "ndtv.", "thehindu.",
    "timesofindia.", "inc42.", "yourstory.", "entrackr.", "vccircle.",
    "analyticsindiamag.", "analyticsvidhya.", "geeksforgeeks.",
    "investopedia.", "statista.", "crunchbase.", "tracxn.", "pitchbook.",
    "g2.", "capterra.", "glassdoor.", "indeed.", "naukri.",
    "slideshare.", "scribd.", "academia.", "researchgate.",
    "amazon.", "flipkart.", "play.google.", "apps.apple.",
    # Press-release wire services — they DISTRIBUTE news, they aren't a company
    # competing in the topic's market. These show up constantly in headline
    # bylines ("via Business Wire", "PR Newswire") and get mis-extracted as brands.
    "businesswire.", "prnewswire.", "globenewswire.", "prweb.", "einpresswire.",
    "newswire.",
    # Generic dev/doc/package hosting platforms — a company's docs living on
    # github.com/readthedocs.io doesn't make GitHub the competitor.
    "github.", "gitlab.", "bitbucket.", "readthedocs.", "npmjs.", "pypi.org",
    "stackoverflow.", "stackexchange.",
}

def _is_skip(d: str) -> bool:
    return any(s in d for s in _SKIP)


# ── Name extraction from news headlines ───────────────────────────────────────

# Matches 1-4 word capitalized phrases (likely proper nouns / brand names)
_CAP_PHRASE = re.compile(
    r"\b([A-Z][A-Za-z0-9&'.\-]{1,25}"
    r"(?:\s+[A-Z][A-Za-z0-9&'.\-]{1,25}){0,3})\b"
)

# Words that are definitely not company names
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "has", "have",
    "had", "will", "would", "could", "should", "may", "might", "new", "big",
    "top", "best", "how", "why", "what", "who", "when", "where", "india",
    "indian", "global", "market", "company", "companies", "startup",
    "funding", "raises", "launch", "launches", "announces", "report",
    "says", "revenue", "growth", "ipo", "deal", "year", "quarter",
    "million", "billion", "percent", "tuesday", "monday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february",
    "march", "april", "june", "july", "august", "september", "october",
    "november", "december", "q1", "q2", "q3", "q4", "ltd", "inc", "pvt",
}


# Common English words that get capitalized simply for starting a sentence/headline
# or being a generic term — NOT because they're a brand name. This is the primary
# source of false positives like "This", "Vector", "ESTC" (acronym noise).
_SENTENCE_STARTERS_AND_GENERIC = {
    "this", "that", "these", "those", "here", "there", "now", "today", "meanwhile",
    "vector", "vectors", "database", "databases", "search", "cloud", "data",
    "platform", "solution", "solutions", "technology", "technologies", "system",
    "systems", "engine", "engines", "index", "indexing", "embedding", "embeddings",
    "model", "models", "api", "sdk", "open", "source", "enterprise", "startup",
    "startups", "series", "round", "week", "month", "according", "however",
    "additionally", "furthermore", "moreover", "overall", "recently", "currently",
    "following", "amid", "despite", "as", "it", "its", "their", "his", "her",
    # Generic marketing/positioning nouns that get capitalized as headline
    # emphasis ("the market Leader", "an industry Pioneer") but are not brands.
    "leader", "leaders", "leading", "pioneer", "pioneers", "innovator",
    "innovators", "provider", "providers", "player", "players", "vendor",
    "vendors", "giant", "giants", "champion", "disruptor", "disruptors",
    # Plain common English nouns that regularly get capitalized at the start
    # of a headline clause or in title case ("Image recognition tool...",
    # "Credit scores rise...") and then get mistaken for a brand once a
    # substring-matching domain resolver finds SOME company whose domain
    # happens to contain the word (imagecomics.com, annualcreditreport.com).
    # This list is intentionally broad/generic rather than topic-specific.
    "image", "images", "credit", "credits", "code", "codes", "mail", "news",
    "docs", "page", "pages", "home", "shop", "store", "bank", "health",
    "life", "care", "work", "works", "team", "group", "groups", "world",
    "digital", "smart", "prime", "plus", "pro", "max", "hub", "labs",
    "corp", "tech", "app", "apps", "web", "net", "link", "links", "chart",
    "charts", "score", "scores", "report", "reports", "guide", "guides",
    "review", "reviews", "list", "lists", "deal", "deals", "sale", "sales",
}


# Marketing-compound suffixes that regularly get capitalized in headlines but are
# adjectives describing a product, not a company name (e.g. "AI-native", "Cloud-based").
_MARKETING_COMPOUND_SUFFIX = re.compile(
    r"-(native|powered|based|driven|first|ready|enabled|as-a-service)$", re.IGNORECASE
)


def _looks_like_brand(phrase: str) -> bool:
    """Filters out sentence-initial capitalized common words and short acronym
    noise, keeping genuine multi-word proper nouns or well-formed single-word
    brand names (mixed case, unusual spelling, or 4+ chars not in the stoplist)."""
    words = phrase.split()
    lowered = [w.lower() for w in words]

    # Reject if EVERY word is a known generic/sentence-starter term.
    if all(w in _SENTENCE_STARTERS_AND_GENERIC for w in lowered):
        return False

    # Reject if ANY word is a known generic/marketing term — this catches
    # phrases like "Leader Pricing" where only one word is generic but the
    # whole phrase is still not a brand name. (Previously only an "all words"
    # check existed, which let "Leader Pricing" and similar slip through.)
    if any(w in _SENTENCE_STARTERS_AND_GENERIC for w in lowered):
        return False

    # Reject ALL-CAPS multi-word phrases — almost always a wire-service byline
    # ("BUSINESS WIRE", "PR NEWSWIRE") or a headline running in caps, not a brand.
    if len(words) >= 2 and phrase == phrase.upper():
        return False

    # Reject marketing-compound adjectives like "AI-native", "Cloud-powered" —
    # these describe a product category, not a company.
    if _MARKETING_COMPOUND_SUFFIX.search(phrase):
        return False

    # For single-word phrases, be strict: reject if it's a generic/common word,
    # or if it's a short all-caps acronym we can't verify (e.g. "ESTC").
    if len(words) == 1:
        w = words[0]
        if lowered[0] in _SENTENCE_STARTERS_AND_GENERIC:
            return False
        if w.isupper() and len(w) <= 5:
            # Bare short acronyms are too ambiguous to trust without corroboration
            # elsewhere; the frequency threshold in suggest_competitors() still
            # allows it through if it appears often enough, but we no longer treat
            # it as an automatic pass.
            return False

    return True


def _extract_names(text: str) -> list[str]:
    """Pull capitalized phrases from a headline that look like brand names."""
    results = []
    for m in _CAP_PHRASE.finditer(text):
        phrase = m.group(1).strip()
        words = phrase.split()
        # Skip single stopwords
        if len(words) == 1 and phrase.lower() in _STOPWORDS:
            continue
        # Skip phrases that ARE stopwords
        if all(w.lower() in _STOPWORDS for w in words):
            continue
        # Skip purely numeric
        if re.match(r"^[\d\s%$]+$", phrase):
            continue
        # Skip very short single chars
        if len(phrase) < 3:
            continue
        # Skip sentence-initial generic words / weak single-word acronyms
        if not _looks_like_brand(phrase):
            continue
        results.append(phrase)
    return results


# ── Domain resolver ───────────────────────────────────────────────────────────

def _resolve(name: str) -> str | None:
    """Find official domain for company name. Returns domain string or None."""
    query = f"{name} official site"
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                url = r.get("href", "") or r.get("url", "") or ""
                d = _domain(url)
                if not d or _is_skip(d):
                    continue
                # Prefer domains containing a token of the name
                tok = re.sub(r"[^a-z0-9]", "", name.lower())[:8]
                dc  = re.sub(r"[^a-z0-9]", "", d)
                if tok and tok[:5] in dc:
                    return d
                # Accept first non-skip result as fallback
                return d
    except Exception:
        pass
    return None


def _governance_sanity_check(name: str, domain: str) -> bool:
    """Final safety net applied right before a candidate is accepted, independent
    of the extraction-stage filters above. This exists because extraction-stage
    filters can be bypassed by upstream changes (e.g. an LLM-based discovery
    agent that doesn't go through _extract_names at all) — so any caller adding
    names to a suggestion list should run them through this check too.

    Rejects:
      - names that are purely/partially built from generic marketing terms
      - names whose resolved domain doesn't share any token with the name
        (a strong signal the "resolution" just grabbed an unrelated top result)
    """
    if not name or not domain:
        return False

    lowered_words = [w.lower().strip(".,'\"") for w in name.split()]
    if any(w in _SENTENCE_STARTERS_AND_GENERIC for w in lowered_words):
        return False
    if all(w in _STOPWORDS for w in lowered_words):
        return False

    # Require the name to make up a SUBSTANTIAL portion of the domain's core
    # label, not just appear anywhere as a substring. A naive "is substring"
    # check lets "image" pass for "imagecomics.com" or "credit" pass for
    # "annualcreditreport.com" — both technically contain the word but are
    # unrelated companies the resolver latched onto because the name is a
    # common dictionary word. Requiring the name to cover most of the
    # domain's core label (ignoring TLD/subdomain parts) filters those out
    # while still allowing legitimate matches like "Oracle" -> "oracle.com"
    # or "Qdrant" -> "qdrant.tech".
    name_core = re.sub(r"[^a-z0-9]", "", name.lower())
    # Use only the first label of the domain (before the first dot) as the
    # "core" — this is the part that actually identifies the company.
    domain_core = re.sub(r"[^a-z0-9]", "", domain.lower().split(".")[0])
    if not name_core or not domain_core:
        return False
    if name_core not in domain_core:
        return False
    # The name must account for a large majority of the domain's core label.
    # (e.g. "oracle" is 100% of "oracle"; "image" is only ~45% of
    # "imagecomics" and gets rejected.)
    if len(name_core) / max(len(domain_core), 1) < 0.7:
        return False

    return True


# ── Public API ────────────────────────────────────────────────────────────────

def suggest_competitors(topic: str) -> list[dict]:
    """Auto-suggest competitors for *topic* using DDG News headlines.

    Returns up to 8 [{"name": str, "domain": str, "confidence": float}].
    Never touches SearchBudget.
    """
    queries = [
        f"{topic} company news",
        f"{topic} startup funding",
        # Replaced '{topic} market leaders' — that query wording is an SEO-blog
        # magnet (posts titled things like "Why Leader Pricing Matters in a
        # Competitive Market") that surfaces generic marketing copy rather than
        # real company names. '{topic} competitors' targets pages that actually
        # name and compare real companies.
        f"{topic} competitors",
    ]

    name_freq: dict[str, int] = {}
    DDGS = _get_ddgs()

    for query in queries:
        try:
            with DDGS() as ddgs:
                # Use news search — much cleaner company names in headlines
                for r in ddgs.news(query, max_results=15):
                    title = r.get("title", "") or ""
                    body  = r.get("body",  "") or r.get("excerpt", "") or ""
                    for text in [title, body[:200]]:
                        for name in _extract_names(text):
                            name_freq[name] = name_freq.get(name, 0) + 1
        except Exception:
            # Fallback to text search if news not available
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=10):
                        title = r.get("title", "") or ""
                        for name in _extract_names(title):
                            name_freq[name] = name_freq.get(name, 0) + 1
            except Exception:
                continue

    if not name_freq:
        return []

    # Keep names that appeared 2+ times (reduces noise dramatically)
    # Fall back to top-10 by freq if nothing hits threshold
    frequent = {n: f for n, f in name_freq.items() if f >= 2}
    if not frequent:
        frequent = dict(sorted(name_freq.items(), key=lambda x: x[1], reverse=True)[:10])

    ranked = sorted(frequent.items(), key=lambda x: x[1], reverse=True)

    # Resolve domains for top candidates
    suggestions: list[dict] = []
    seen_domains: set[str] = set()

    for name, freq in ranked:
        if len(suggestions) >= 8:
            break
        d = _resolve(name)
        if not d or _is_skip(d) or d in seen_domains:
            continue
        # Governance-layer sanity check — independent final gate before a
        # name/domain pair is accepted into the suggestion list.
        if not _governance_sanity_check(name, d):
            continue
        seen_domains.add(d)
        confidence = round(min(0.5 + freq * 0.1, 0.95), 2)
        suggestions.append({"name": name, "domain": d, "confidence": confidence})

    return suggestions


def validate_competitor(name: str) -> dict | None:
    """Validate a manually entered name. Returns {"name", "domain"} or None."""
    if not name or not name.strip():
        return None
    d = _resolve(name.strip())
    if not d:
        return None
    if not _governance_sanity_check(name.strip(), d):
        return None
    return {"name": name.strip(), "domain": d}