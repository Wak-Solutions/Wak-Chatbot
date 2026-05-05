"""_handler.py — public navigation API: walk a customer one level at a time through the menu tree."""

import logging

from ._config import _load_menu_config
from ._state import _MenuState, _get_state, _set_state, clear_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _label(node) -> str:
    return node if isinstance(node, str) else node.get("label", "")


def _children(node) -> list:
    return [] if isinstance(node, str) else (node.get("subItems") or [])


def _format_level(nodes: list, header: str | None = None) -> str:
    lines = []
    if header:
        lines.append(header)
    for i, node in enumerate(nodes, 1):
        lines.append(f"{i}. {_label(node)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def format_top_level(company_id: int) -> str | None:
    """
    Return a formatted string of the top-level menu items only, or None if
    no menu is configured. Does not modify any state.
    """
    items = await _load_menu_config(company_id)
    if not items:
        return None
    return _format_level(items)


async def start(phone: str, company_id: int, conversation_id: str) -> str | None:
    """
    (Re)initialise navigation at the top level for this customer.
    Returns the formatted top-level menu, or None if no menu is configured.
    Called after every bot reply so the customer can always start navigating.
    """
    items = await _load_menu_config(company_id)
    if not items:
        return None
    _set_state(phone, company_id, _MenuState(path=[], conversation_id=conversation_id))
    return _format_level(items)


async def handle(
    phone: str,
    company_id: int,
    message: str,
    conversation_id: str,
) -> tuple[str | None, str | None]:
    """
    Process a customer message during menu navigation.

    Returns (reply, leaf_label):
      reply       — Text to send the customer, or None if not in menu mode.
      leaf_label  — Breadcrumb of the final selection when a leaf is reached
                    (e.g. "Product Inquiry > AI Services > Market Pulse"), or None.

    Caller logic:
      - reply is not None, leaf_label is None  → send reply, done (mid-tree level)
      - reply is None,     leaf_label is set   → leaf reached; pass label to OpenAI
      - reply is None,     leaf_label is None  → not in menu mode; use normal OpenAI path
    """
    items = await _load_menu_config(company_id)
    if not items:
        return None, None

    state = _get_state(phone, company_id, conversation_id)
    if state is None:
        return None, None

    text = message.strip()

    # Non-numeric input exits the menu and falls through to the LLM
    if not text.isdigit():
        clear_state(phone, company_id)
        return None, None

    # Resolve current level's nodes by walking the stored path
    current_nodes = items
    for idx in state.path:
        current_nodes = _children(current_nodes[idx])

    choice = int(text)
    if choice < 1 or choice > len(current_nodes):
        reply = _format_level(
            current_nodes,
            f"Please choose a valid option (1–{len(current_nodes)}):",
        )
        return reply, None

    selected = current_nodes[choice - 1]
    new_path = state.path + [choice - 1]

    # Build human-readable breadcrumb for the chosen path
    breadcrumb_nodes = items
    labels: list[str] = []
    for idx in new_path:
        node = breadcrumb_nodes[idx]
        labels.append(_label(node))
        breadcrumb_nodes = _children(node)
    breadcrumb = " > ".join(labels)

    kids = _children(selected)
    if not kids:
        # Leaf node — selection complete; hand off to OpenAI
        clear_state(phone, company_id)
        logger.info(
            "Leaf reached — phone: ...%s, selection: %s",
            phone[-4:],
            breadcrumb,
        )
        return None, breadcrumb

    # Has children — show next level and update state
    _set_state(phone, company_id, _MenuState(path=new_path, conversation_id=conversation_id))
    logger.info(
        "Navigated to level %d — phone: ...%s, path: %s",
        len(new_path),
        phone[-4:],
        breadcrumb,
    )
    return _format_level(kids), None
