"""Section 9.1 — 'Generate Reply' calls OpenAI with the message content and
the linked invoice/ledger context, drafting a suggested reply. It is ALWAYS a
draft into the compose box, never auto-sent — the router/inbox_service layer
enforces that a human presses Send separately."""

from openai import OpenAI

from app.config import settings

MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "You are drafting a reply on behalf of Omega Scales, a weighing-scale equipment business in Karachi, "
    "to a customer's email about an invoice. Be concise, polite, and factual. Only state figures given to "
    "you in the context below — never invent an amount, date, or balance."
)


def _build_context(message: dict, invoice: dict | None) -> str:
    lines = [
        f"Customer email subject: {message.get('subject', '')}",
        f"Customer email content: {message.get('snippet', '')}",
    ]
    if invoice:
        lines += [
            f"Linked invoice #{invoice.get('invoice_no')}:",
            f"  Total amount: Rs. {invoice.get('total_amount')}",
            f"  Current balance: Rs. {invoice.get('current_balance')}",
            f"  Due date: {invoice.get('due_date')}",
            f"  Status: {invoice.get('invoice_status')}",
        ]
    else:
        lines.append("No specific invoice is linked to this message.")
    return "\n".join(lines)


def generate_reply_draft(message: dict, invoice: dict | None = None) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    context = _build_context(message, invoice)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Draft a reply to this customer email:\n\n{context}"},
        ],
    )
    return response.choices[0].message.content
