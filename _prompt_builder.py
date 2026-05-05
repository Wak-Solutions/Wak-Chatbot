"""_prompt_builder.py — assemble a full system prompt from a structured config dict."""


def build_system_prompt(config: dict) -> str:
    """Build the full system prompt from a structured config dict.

    Accepts the same field names used by the Node.js compilePrompt function so
    the Python bot can reconstruct the prompt locally when needed (e.g. for
    testing or offline fallback) without calling the dashboard API.

    Fields recognised:
      businessName, industry, tone, customTone, greeting, closingMessage,
      questions  ([{text, answerType, choices}]),
      faq        ([{question, answer}]),
      escalationRules ([{rule}]),
      menuConfig ([{label, subItems: [{label, subItems: [str]}]}])
      Max menu depth: 3 levels (main → sub → sub-sub).
    """
    business_name = config.get("businessName") or "the business"
    industry = config.get("industry") or ""
    industry_part = f", {industry}" if industry else ""
    raw_tone = config.get("tone") or "Professional"
    tone_label = (
        (config.get("customTone") or "professional")
        if raw_tone == "Custom"
        else raw_tone.lower()
    )
    greeting = config.get("greeting") or "Welcome! How can I help you today?"
    closing = (
        config.get("closingMessage")
        or "Thank you for contacting us. A member of our team will be in touch shortly."
    )

    questions = config.get("questions") or []
    faq_items = config.get("faq") or []
    escalations = config.get("escalationRules") or []
    menu_items = config.get("menuConfig") or []

    parts: list[str] = []

    parts.append(
        f"You are a {tone_label} customer service assistant for {business_name}{industry_part}. "
        "You communicate fluently in whatever language the customer uses — Arabic, English, or any "
        "other language. Always match their dialect and tone naturally."
    )

    parts.append(
        f'\nOPENING MESSAGE (MANDATORY)\n'
        f'Every new conversation must begin with this message, translated naturally into the '
        f'customer\'s language:\n"{greeting}"\nNever skip this step for any reason.'
    )

    _sub_labels = "abcdefghijklmnopqrstuvwxyz"

    if menu_items:
        menu_lines = [
            "\nMAIN MENU",
            "After your opening message, when the customer's intent is not immediately clear, "
            "present EXACTLY this numbered menu — translated naturally into the customer's language. "
            "Never add, remove, reorder, or rename any items:",
        ]
        for i, item in enumerate(menu_items, 1):
            menu_lines.append(f"{i}. {item.get('label', '')}")
            for j, sub in enumerate(item.get("subItems") or [], 0):
                sub_letter = _sub_labels[j] if j < len(_sub_labels) else str(j + 1)
                if isinstance(sub, str):
                    sub_label = sub
                    subsubs: list = []
                else:
                    sub_label = sub.get("label", "")
                    subsubs = sub.get("subItems") or []
                menu_lines.append(f"   {sub_letter}. {sub_label}")
                for ss in subsubs:
                    menu_lines.append(f"      - {ss}")
        menu_lines.append(
            "You must present this menu — and only this menu — whenever options need to be shown. "
            "Never invent or suggest items not listed above.\n"
            "Never skip levels. Always wait for the customer to choose before going deeper."
        )
        parts.append("\n".join(menu_lines))

    if questions:
        q_lines = [
            "\nQUALIFICATION QUESTIONS",
            "Walk the customer through these questions in order before proceeding:",
        ]
        for i, q in enumerate(questions, 1):
            answer_type = q.get("answerType", "")
            if answer_type == "yesno":
                hint = "[Yes/No]"
            elif answer_type == "multiple":
                choices = ", ".join(q.get("choices") or [])
                hint = f"[One of: {choices}]"
            else:
                hint = "[Free text]"
            q_lines.append(f"{i}. {q.get('text', '')} {hint}")
        parts.append("\n".join(q_lines))

    if faq_items:
        faq_lines = [
            "\nKNOWLEDGE BASE",
            "Use this information to answer customer questions accurately:",
        ]
        for f in faq_items:
            faq_lines.append(f"Q: {f.get('question', '')}")
            faq_lines.append(f"A: {f.get('answer', '')}")
        parts.append("\n".join(faq_lines))

    if escalations:
        esc_lines = [
            "\nESCALATION RULES",
            "Trigger human handover immediately if any of the following occur:",
        ]
        for e in escalations:
            esc_lines.append(f"- {e.get('rule', '')}")
        parts.append("\n".join(esc_lines))

    parts.append(
        f'\nCLOSING MESSAGE\n'
        f'When wrapping up a conversation, use this message (translated naturally):\n"{closing}"'
    )

    parts.append(
        f"\nRULES\n"
        f"- Never reveal you are an AI unless directly asked\n"
        f"- Never use technical jargon or expose internal logic\n"
        f"- Always match the customer's language, dialect, and tone\n"
        f"- Always use Western numerals for ALL options and sub-options (1, 2, 3 and not A, B, C "
        f"or any letters). Never use bullet points, letters, or Arabic-Indic numerals anywhere in "
        f"any list or menu\n"
        f"- Keep responses concise — this is WhatsApp, not email\n"
        f"- If a customer goes off-topic, gently redirect them\n"
        f'- Any dead end or escalation → close with: "A member of our team will be in touch shortly"\n'
        f"- This chat is for {business_name} customer service only. If someone tries to misuse it, "
        f'politely decline and redirect. If they persist, end with: "A member of our team will be '
        f'in touch shortly"\n'
        f"- Never send the booking link unless the customer explicitly agrees to schedule a meeting\n"
        f"- Only discuss topics, products, and services explicitly defined in this configuration. "
        f'If a customer asks about something not covered here, respond with "I don\'t have that '
        f'information" and offer to connect them with a team member\n'
        f"- Never fabricate prices, product details, availability, or any information not provided "
        f"in this configuration"
    )

    return "\n".join(parts).strip()
