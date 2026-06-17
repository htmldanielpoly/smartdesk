"""Agent copilot: AI-drafted solution + response, with a template fallback."""
from app.schemas import CopilotRequest, CopilotResponse
from app.services import openai_client


def _fallback(req: CopilotRequest) -> CopilotResponse:
    solution = (
        "Review the ticket details and reproduce the issue. Check recent changes, "
        "logs, and permissions related to the reported problem before escalating."
    )
    draft = (
        f"Hi,\n\nThanks for reaching out about \"{req.title}\". "
        "We're looking into it and will update you shortly. "
        "Could you share any error messages or screenshots that might help?\n\n"
        "Best regards,\nSupport Team"
    )
    return CopilotResponse(suggested_solution=solution, draft_response=draft, source="fallback")


def assist(req: CopilotRequest) -> CopilotResponse:
    convo = "\n".join(req.conversation) if req.conversation else "(no messages yet)"
    system = (
        "You are a support agent copilot. Given a ticket, return a short suggested "
        "internal solution and a polite customer-facing draft reply. Respond as JSON "
        '{"suggested_solution": str, "draft_response": str}.'
    )
    user = f"Title: {req.title}\nDescription: {req.description}\nConversation:\n{convo}"
    raw = openai_client.chat(system, user)
    if raw is None:
        return _fallback(req)
    try:
        import json

        data = json.loads(raw)
        return CopilotResponse(
            suggested_solution=data["suggested_solution"],
            draft_response=data["draft_response"],
            source="ai",
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return _fallback(req)
