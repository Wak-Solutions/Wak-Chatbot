"""
tools.py — OpenAI tool schema definitions for the WAK bot.

Centralised here so that adding a new tool only requires editing one file
rather than hunting through agent.py.
"""

# OpenAI reads this list and decides when to call each function.
# When it does, it responds with a tool_call instead of a text reply.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": (
                "Look up a customer order in the database using the order number. "
                "Use this when a customer wants to track or check the status of their order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {
                        "type": "string",
                        "description": "The order number provided by the customer, e.g. WAK-001",
                    }
                },
                "required": ["order_number"],
            },
        },
    },
]
