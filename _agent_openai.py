"""_agent_openai.py — OpenAI chat call wrapper plus tool-call dispatch and follow-up turn."""

import json
import logging

import openai

import database
from config import OPENAI_MODEL
from notifications import mask_phone
from tools import TOOLS

logger = logging.getLogger(__name__)


class _OpenAITimeout(Exception):
    """Raised when an OpenAI call times out; carries the user-facing fallback text."""

    def __init__(self, fallback: str):
        self.fallback = fallback
        super().__init__(fallback)


async def run_openai_turn(
    client,
    messages: list,
    customer_phone: str,
    company_id: int,
) -> str | None:
    """
    Run the first OpenAI call, dispatch any tool calls, and (if a tool was used)
    run the follow-up call. Returns the final reply text, or a fallback string
    on timeout. The `messages` list is mutated to include tool messages.

    `client` is passed in so tests that patch `agent.client` are honoured.
    """
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            timeout=30.0,
        )
    except openai.APITimeoutError:
        logger.error(
            "OpenAI timeout — model: %s, phone: %s",
            OPENAI_MODEL,
            mask_phone(customer_phone),
        )
        raise _OpenAITimeout("I'm taking too long to respond. Please try again in a moment.")

    usage = response.usage
    logger.info(
        "OpenAI response — model: %s, prompt_tokens: %s, completion_tokens: %s, phone: %s",
        OPENAI_MODEL,
        usage.prompt_tokens if usage else "n/a",
        usage.completion_tokens if usage else "n/a",
        mask_phone(customer_phone),
    )

    response_message = response.choices[0].message

    if not response_message.tool_calls:
        return response_message.content

    # Append the assistant message once (contains all tool_calls)
    messages.append(response_message)
    for tool_call in response_message.tool_calls:
        function_name = tool_call.function.name
        function_args = json.loads(tool_call.function.arguments)

        logger.info(
            "Tool call — function: %s, phone: %s",
            function_name,
            mask_phone(customer_phone),
        )

        if function_name == "lookup_order":
            try:
                tool_result = await database.lookup_order(
                    order_number=function_args["order_number"],
                    company_id=company_id,
                )
            except Exception as _lookup_exc:
                logger.warning(
                    "lookup_order failed — phone: %s, error: %s",
                    mask_phone(customer_phone),
                    _lookup_exc,
                )
                tool_result = {"error": "Order lookup temporarily unavailable. Please try again."}
        else:
            logger.warning(
                "Unknown tool requested — function: %s", function_name
            )
            tool_result = {"error": f"Unknown tool: {function_name}"}

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result),
            }
        )

    # Second OpenAI call with the tool result included.
    try:
        second_response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            timeout=30.0,
        )
    except openai.APITimeoutError:
        logger.error(
            "OpenAI tool-followup timeout — model: %s, phone: %s",
            OPENAI_MODEL,
            mask_phone(customer_phone),
        )
        raise _OpenAITimeout("I'm taking too long to respond. Please try again in a moment.")
    second_usage = second_response.usage
    logger.info(
        "OpenAI tool-follow-up — model: %s, prompt_tokens: %s, completion_tokens: %s, phone: %s",
        OPENAI_MODEL,
        second_usage.prompt_tokens if second_usage else "n/a",
        second_usage.completion_tokens if second_usage else "n/a",
        mask_phone(customer_phone),
    )
    return second_response.choices[0].message.content
