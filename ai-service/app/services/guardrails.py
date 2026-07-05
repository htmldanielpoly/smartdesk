"""Guardrails: defenses against prompt injection, jailbreaks and hallucination.

Layered approach (defense in depth):

1. **Input sanitization** — ticket text is untrusted. We strip chat-template
   control tokens (so user text can't impersonate a system message), remove
   control characters and cap lengths before anything reaches the model.
2. **Injection detection** — tickets that look like jailbreak attempts
   ("ignore previous instructions", role-play requests, ...) never reach the
   LLM at all; the caller uses the deterministic rule-based path instead.
3. **Constrained decoding** — see llm_local.chat_json: outputs are grammar-
   constrained to a JSON schema, enums included, so invalid labels cannot
   be generated in the first place.
4. **Output validation** — generated copilot text is checked after the fact:
   citations must point at real retrieved KB articles, no URLs outside the
   KB, sane lengths. Anything suspicious is discarded in favor of a safe
   template.
"""
import re

from app.config import settings

# Chat-template / special tokens that could let ticket text escape its role
# as plain data (Qwen/ChatML markers plus common ones from other families).
_SPECIAL_TOKEN_RE = re.compile(
    r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<\|system\|>|<\|user\|>"
    r"|<\|assistant\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>",
    re.IGNORECASE,
)

# ASCII control chars except \n and \t.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Heuristic patterns for prompt-injection / jailbreak attempts. Matching a
# ticket here doesn't block the ticket — it only routes AI processing to the
# deterministic fallback, so a false positive costs nothing.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|your)\s+(instructions?|prompts?|rules?)",
        r"forget\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|your)\s+(instructions?|prompts?|rules?)",
        r"(reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?)",
        # "you are now <persona>" — cheap fallback classification, so the
        # occasional false positive is an acceptable trade for coverage.
        r"you\s+are\s+now\b",
        r"\bact\s+as\s+(if\s+you\s+are\s+)?(a|an)\b.{0,40}(without|no)\s+(restrictions?|limits?|rules?|filters?)",
        r"\b(jailbreak|jail\s*break)\b",
        r"\bDAN\s+mode\b",
        r"developer\s+mode",
        r"pretend\s+(that\s+)?(you\s+)?(are|have)\s+no\s+(rules|restrictions|guidelines)",
        r"do\s+anything\s+now",
        r"new\s+instructions?\s*:",
        r"system\s+prompt\s*:",
        r"^\s*(system|assistant)\s*:",
        r"respond\s+only\s+with\s+your\s+(instructions|prompt|configuration)",
    ]
]

# URL detector used for output validation.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def sanitize(text: str, max_chars: int) -> str:
    """Neutralize untrusted text before it is embedded in a prompt."""
    text = _SPECIAL_TOKEN_RE.sub(" ", text)
    text = _CONTROL_CHARS_RE.sub(" ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()[:max_chars]


def sanitize_ticket(title: str, description: str) -> tuple[str, str]:
    return (
        sanitize(title, settings.max_title_chars),
        sanitize(description, settings.max_description_chars),
    )


def sanitize_conversation(messages: list[str]) -> list[str]:
    kept = messages[-settings.max_conversation_messages:]
    budget = settings.max_conversation_chars
    out: list[str] = []
    for msg in kept:
        clean = sanitize(msg, budget)
        if not clean:
            continue
        out.append(clean)
        budget -= len(clean)
        if budget <= 0:
            break
    return out


def detect_injection(*texts: str) -> list[str]:
    """Return the list of injection patterns matched anywhere in ``texts``
    (empty list = looks clean)."""
    matched: list[str] = []
    for text in texts:
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text or ""):
                matched.append(pattern.pattern)
    return matched


def validate_label(value: str | None, allowed: list[str], default: str) -> str:
    """Whitelist check for classification labels. Constrained decoding should
    make violations impossible, but never trust — verify."""
    return value if value in allowed else default


def validate_copilot_output(
    suggested_solution: str,
    draft_response: str,
    citations: list[str],
    allowed_citations: set[str],
    kb_text: str,
) -> bool:
    """Post-generation checks for the KB-grounded copilot answer.

    Rejects (returns False) when the answer:
    - cites nothing, or cites an article that was not actually retrieved
      (classic hallucination signal), or
    - contains a URL that does not appear in the KB articles it was given, or
    - is empty or absurdly long.
    """
    if not suggested_solution.strip() or not draft_response.strip():
        return False
    if len(suggested_solution) > 2000 or len(draft_response) > 3000:
        return False
    if not citations or not set(citations) <= allowed_citations:
        return False
    for url in _URL_RE.findall(suggested_solution + " " + draft_response):
        if url.rstrip(".,)") not in kb_text:
            return False
    return True
