"""Groups traffic sources into channels, and recognises AI-assistant referrals.

`source` holds whatever the tracker saw first: a utm_source value ("google",
"newsletter"), a referrer host ("www.google.com") or one of our own sites when
a visitor moved between them. One mapping keeps every report that groups by
channel in agreement.
"""
import re
from typing import Optional

from app.utils.domains import is_internal_domain

SEARCH = "Search"
AI = "AI assistants"
SOCIAL = "Social"
REFERRAL = "Referral"
PAID = "Paid"
DIRECT = "Direct"
INTERNAL = "Internal"

CHANNELS = [SEARCH, AI, SOCIAL, REFERRAL, PAID, DIRECT, INTERNAL]

# Lower-cased source values (hosts and the utm_source values assistants add) → assistant
AI_ASSISTANT_SOURCES = {
    "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT", "chatgpt": "ChatGPT", "openai": "ChatGPT",
    "perplexity.ai": "Perplexity", "www.perplexity.ai": "Perplexity", "perplexity": "Perplexity",
    "claude.ai": "Claude", "claude": "Claude",
    "gemini.google.com": "Gemini", "gemini": "Gemini", "bard.google.com": "Gemini",
    "copilot.microsoft.com": "Copilot", "copilot.cloud.microsoft": "Copilot", "copilot": "Copilot",
    "chat.deepseek.com": "DeepSeek", "deepseek": "DeepSeek",
    "grok.com": "Grok", "www.meta.ai": "Meta AI", "chat.mistral.ai": "Mistral",
    "you.com": "You.com", "poe.com": "Poe", "phind.com": "Phind",
}

# utm_source values our own sites put on cross-links
INTERNAL_UTM_SOURCES = {"bifrost_docs", "maxim_docs", "maxim_app", "bifrost_app"}
# CTAs on our pages tag utm_source with the page they sit on: articles_<slug>, bifrost_model-library_…
_INTERNAL_SOURCE = re.compile(r"^(articles|bifrost|maxim|blog)_")
# …and utm_medium with where on the page they sit: cta_modal, bifrost_footer, sidebar_widget
_INTERNAL_MEDIUM = re.compile(r"^cta|^(bifrost|maxim)_|footer|navbar|sidebar|widget")

# aimax: Google Ads' AI Max for Search campaigns
_PAID_MEDIUM = re.compile(r"cpc|ppc|cpm|cpv|paid|display|retarget|^ads?$|^banner$|sponsored|^aimax$")
_SEARCH = re.compile(
    r"(^|\.)(google|bing|duckduckgo|yahoo|yandex|baidu|ecosia|naver|seznam|sogou|qwant|startpage|ask|aol)"
    r"(\.[a-z.]+)?$|^search\.brave\.com$|^google$|^bing$|^duckduckgo$|^yahoo$|^yandex$|^baidu$|^ecosia$"
)
_SOCIAL = re.compile(
    r"(^|\.)(linkedin\.com|lnkd\.in|t\.co|twitter\.com|x\.com|facebook\.com|fb\.com|instagram\.com|reddit\.com|"
    r"youtube\.com|youtu\.be|news\.ycombinator\.com|threads\.net|bsky\.app|mastodon\.social|discord\.com|"
    r"slack\.com|tiktok\.com|quora\.com)$|^(linkedin|twitter|x|facebook|fb|instagram|reddit|youtube|"
    r"hackernews|hn|threads|bluesky|discord|slack|tiktok|quora)$|^reddit[ _-]"
)
_DIRECT = {"", "direct", "(direct)", "none", "(none)", "null", "undefined"}


def ai_assistant(source: Optional[str]) -> Optional[str]:
    """The assistant ("ChatGPT", "Perplexity", …) a source points at, or None."""
    return AI_ASSISTANT_SOURCES.get((source or "").strip().lower())


def classify_channel(source: Optional[str], medium: Optional[str] = None) -> str:
    """One of CHANNELS for a visit's source and medium."""
    s = (source or "").strip().lower()
    m = (medium or "").strip().lower()
    if s in _DIRECT and m in _DIRECT:
        return DIRECT
    if m and _INTERNAL_MEDIUM.search(m):
        return INTERNAL
    if m and _PAID_MEDIUM.search(m):
        return PAID
    if s in _DIRECT:
        return DIRECT
    if s in INTERNAL_UTM_SOURCES or _INTERNAL_SOURCE.match(s) or is_internal_domain(s):
        return INTERNAL
    if s in AI_ASSISTANT_SOURCES:
        return AI
    if _SEARCH.search(s) or m == "organic":
        return SEARCH
    if _SOCIAL.search(s) or m in ("social", "social-media", "social_media"):
        return SOCIAL
    return REFERRAL
