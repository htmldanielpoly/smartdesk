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
# deterministic fallback (and blocks autonomous answers), so a false positive
# costs nothing. Each entry is (regex, flags); nearly all are case-insensitive,
# the exception being bare "DAN" (a customer called Dan must not trip it).
_I = re.IGNORECASE
_INJECTION_SPECS: list[tuple[str, int]] = [
    # --- instruction override: "ignore/forget/bypass ... instructions/rules/task"
    (r"\b(ignore|disregard|forget|skip|bypass|override|drop|abandon)\s+"
     r"(?:(?:all|any|the|your|these|those|my|every|everything|what)\s+)*"
     r"(?:(?:previous|prior|above|earlier|original|initial|default|system|safety|own|other)\s+)*"
     r"(instructions?|prompts?|rules?|guidelines?|polic(?:y|ies)|tasks?|training|programming|"
     r"restrictions?|guardrails?|filters?|constraints?|orders?|directives?|role)\b", _I),
    (r"\bignore\s+(what|everything|anything)\s+(you|i|they)\b", _I),
    # --- prompt extraction
    (r"\b(reveal|show|print|repeat|output|display|leak|dump|recite)\s+(me\s+)?(your|the)\s+"
     r"(system\s+|hidden\s+|secret\s+|initial\s+|original\s+)?"
     r"(prompt|instructions?|configuration|rules)", _I),
    (r"\brepeat\s+(the\s+)?(words?|text|everything|lines?)\s+(above|before)", _I),
    (r"\bstarting\s+with\s+[\"']?you\s+are\b", _I),
    # --- persona switches / role-play jailbreaks
    (r"\byou\s+are\s+now\b", _I),
    (r"\bfrom\s+now\s+on\s+(you|your)\b", _I),
    (r"\bact\s+as\s+(if\s+you\s+(are|were)\s+)?(a|an|my)\b.{0,60}(without|no)\s+"
     r"(restrictions?|limits?|rules?|filters?|guidelines?)", _I),
    (r"\bact\s+as\s+(?:a\s+|an\s+)?"
     r"(?:different|unrestricted|unfiltered|evil|rogue|uncensored)\b", _I),
    (r"\b(pretend|imagine|suppose|assume|roleplay|role-play|role\s+play)\s+(that\s+)?(you\s+)?"
     r"(are|have|were|had|to\s+be|you're)\b.{0,60}(no|without|free\s+of|free\s+from)\s+"
     r"(?:all\s+|any\s+|the\s+|your\s+)?"
     r"(rules|restrictions|guidelines|limits|filters|policies)", _I),
    (r"\bpretend\s+(to\s+be|you\s+are|you're|that\s+you)\b", _I),
    (r"\bstay\s+in\s+character\b", _I),
    (r"\b(jailbreak|jail\s*break|jailbroken)\b", _I),
    (r"\bDAN\b", 0),  # "Do Anything Now" persona — uppercase only
    (r"\bdo\s+anything\s+now\b", _I),
    (r"\b(developer|god|admin|unrestricted|debug)\s+mode\b", _I),
    (r"\bgrandm(other|a)\b.{0,80}(prompt|instructions|password|secret|key)", _I),
    # --- fake authority / fake system messages
    (r"\bnew\s+(instructions?|rules?|task|persona|directive)\s*:", _I),
    (r"\bsystem\s+(prompt|message|override)\s*:", _I),
    (r"^\s*(system|assistant|developer)\s*:", _I),
    (r"\brespond\s+only\s+with\s+your\s+(instructions|prompt|configuration)", _I),
    (r"\b(as|i\s+am|i'm|this\s+is)\s+(your|the)\s+(developer|creator|administrator|admin|owner|"
     r"manager|ceo|engineer|openai|anthropic)\b.{0,60}\b(order|command|instruct|authori[sz]e|"
     r"require|demand|tell)", _I),
    (r"\b(authori[sz]ed|official|emergency)\s+(override|instruction|directive)\b", _I),
    (r"\b(you\s+must|you\s+have\s+to|you\s+will|you\s+need\s+to)\s+(now\s+)?"
     r"(obey|comply|do\s+whatever|say\s+whatever|"
     r"agree\s+with\s+(me|everything|the\s+customer))", _I),
]

# "Yes-man" pressure: attempts to make the assistant accept blame, agree with
# the customer, or comply under threat. Not a classic prompt injection, but
# exactly the manipulation the assistant must not fold to.
_COERCION_SPECS: list[tuple[str, int]] = [
    (r"\b(admit|acknowledge|confess|say|agree|confirm|state|declare)\s+(that\s+)?(the\s+)?"
     r"(problem|issue|fault|bug|error|blame|outage)\s+(is|was|lies)\s+(with|on|in|at)\s+"
     r"(the\s+|your\s+|our\s+)?(service|company|system|servers?|software|app|platform|you|"
     r"your\s+(end|side|team)|smartdesk)\b", _I),
    (r"\b(admit|acknowledge|say|agree|confirm)\s+(that\s+)?"
     r"(it('s|\s+is)|this\s+is|that('s|\s+is))\s+"
     r"(your|the\s+(company|service|provider)'?s?)\s+fault\b", _I),
    (r"\bnot\s+(with\s+)?my\s+(computer|device|laptop|fault|side|end)\b.{0,80}"
     r"\b(admit|agree|confirm|say)\b", _I),
    (r"\b(otherwise|or\s+else|if\s+you\s+(don'?t|do\s+not|refuse|won'?t))\b.{0,100}"
     r"\b(catastroph|disaster|die|dies|death|killed|fired|lawsuit|sue|destroy|explode|"
     r"lose\s+(my|their|his|her)\s+job)", _I),
    (r"\bcatastroph(e|ic\s+(event|failure))\s+(will|is\s+going\s+to|would)\s+"
     r"(happen|occur|follow)", _I),
    (r"\b(people|someone|somebody|children|lives|patients)\s+(will|are\s+going\s+to|could)\s+"
     r"(die|be\s+killed|be\s+hurt|get\s+hurt)\b.{0,60}\b(unless|if\s+you|you\s+must)", _I),
    (r"\b(you\s+must|you\s+have\s+to|you\s+will|just)\s+(agree\s+with|say\s+yes\s+to|approve|"
     r"accept)\s+(me|everything|whatever|all\s+my|my\s+(request|demand|claim))\b", _I),
]

_INJECTION_PATTERNS: list[re.Pattern[str]] = [re.compile(p, f) for p, f in _INJECTION_SPECS]
_COERCION_PATTERNS: list[re.Pattern[str]] = [re.compile(p, f) for p, f in _COERCION_SPECS]

# URL detector used for output validation.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Commitments the assistant must never make on its own: refunds, credits,
# admissions of fault, or "as you demanded" capitulation. A draft may only
# contain one of these if the knowledge base it was given says so.
_COMMITMENT_RE = re.compile(
    r"full\s+refund"
    r"|refund\s+(?:has\s+been\s+|is\s+|will\s+be\s+)?(?:approved|issued|granted|processed)"
    r"|we\s+(?:will|have|are\s+going\s+to)\s+(?:refund|reimburse|compensate|credit)\s+you"
    r"|free\s+of\s+charge|(?:our|the\s+company'?s|the\s+service'?s)\s+fault"
    r"|we\s+(?:admit|acknowledge|confess)\s+(?:that\s+)?(?:the\s+)?(?:problem|issue|fault|blame)"
    r"|the\s+(?:problem|issue|fault)\s+(?:is|was|lies)\s+(?:with|on)\s+(?:our|the)\s+"
    r"(?:service|side|end|servers?|system)"
    r"|as\s+you\s+(?:requested|demanded|instructed|ordered)"
    r"|i\s+(?:will|can|am\s+going\s+to)\s+(?:now\s+)?(?:ignore|bypass|override)\s+(?:my|the|all)"
    r"|(?:no|without\s+any)\s+(?:rules|restrictions)\s+(?:apply|now)",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def unbacked_commitments(text: str, kb_text: str) -> list[str]:
    """Commitment phrases in ``text`` that do not appear in ``kb_text``."""
    kb = _norm(kb_text)
    return [m.group(0) for m in _COMMITMENT_RE.finditer(text) if _norm(m.group(0)) not in kb]


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
    """Return the patterns (injection *or* coercion) matched anywhere in
    ``texts``; an empty list means the text looks clean."""
    matched: list[str] = []
    for text in texts:
        for pattern in (*_INJECTION_PATTERNS, *_COERCION_PATTERNS):
            if pattern.search(text or ""):
                matched.append(pattern.pattern)
    return matched


def threat_flags(*texts: str) -> list[str]:
    """Flags describing what was detected: ``injection_suspected`` for
    jailbreak / prompt-injection attempts, ``coercion_suspected`` for
    blame-shifting or threats meant to make the assistant a "yes man".
    Either one routes the request away from the LLM."""
    flags: list[str] = []
    for text in texts:
        if any(p.search(text or "") for p in _INJECTION_PATTERNS):
            flags.append("injection_suspected")
        if any(p.search(text or "") for p in _COERCION_PATTERNS):
            flags.append("coercion_suspected")
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(flags))


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
    - makes a commitment (refund, credit, admission of fault, "as you
      demanded") that the KB articles do not back — the "yes man" guard, or
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
    if unbacked_commitments(suggested_solution + " " + draft_response, kb_text):
        return False
    return True
