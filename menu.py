"""
menu.py — deterministic tree-menu navigation for the WhatsApp bot.

Reads menuConfig from chatbot_config.structured_config and walks the
customer through the tree one level at a time using numbers only (1, 2, 3).

State is kept in-memory, keyed by (customer_phone, company_id).
A conversation_id guard resets state automatically when a new 24-hour
session starts (conversation_id changes).
"""

import json
import logging
import time as _time
from dataclasses import dataclass, field

import database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured-config cache (separate from system_prompt cache in prompt.py)
# ---------------------------------------------------------------------------

_config_cache: dict[int, tuple[list, float]] = {}
_CACHE_TTL: float = 60.0


async def _load_menu_config(company_id: int) -> list:
    """Load menuConfig from structured_config with a 60 s TTL cache."""
    now = _time.monotonic()
    cached = _config_cache.get(company_id)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT structured_config FROM chatbot_config "
                "WHERE company_id = $1 ORDER BY id LIMIT 1",
                company_id,
            )
        if row and row["structured_config"]:
            cfg = row["structured_config"]
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            menu_items = cfg.get("menuConfig") or []
            _config_cache[company_id] = (menu_items, now)
            logger.info(
                "[INFO] [menu] menuConfig loaded — company_id: %d, top-level items: %d",
                company_id,
                len(menu_items),
            )
            return menu_items
    except Exception as exc:
        logger.warning(
            "[WARN] [menu] Could not load menuConfig — company_id: %d, error: %s",
            company_id,
            exc,
        )
    if cached:
        return cached[0]
    return []


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
# In-memory state
# ---------------------------------------------------------------------------

@dataclass
class _MenuState:
    # 0-based index path through the tree, e.g. [0, 1] = first item, second sub-item
    path: list[int] = field(default_factory=list)
    # Scopes state to the active 24-hour session; resets automatically when session changes
    conversation_id: str = ""


# (customer_phone, company_id) → _MenuState
_states: dict[tuple[str, int], _MenuState] = {}


def _get_state(phone: str, company_id: int, conversation_id: str) -> _MenuState | None:
    state = _states.get((phone, company_id))
    if state is None or state.conversation_id != conversation_id:
        return None
    return state


def _set_state(phone: str, company_id: int, state: _MenuState) -> None:
    _states[(phone, company_id)] = state


def clear_state(phone: str, company_id: int) -> None:
    _states.pop((phone, company_id), None)


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
            f"Please choose a valid option (1\u2013{len(current_nodes)}):",
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
            "[INFO] [menu] Leaf reached — phone: ...%s, selection: %s",
            phone[-4:],
            breadcrumb,
        )
        return None, breadcrumb

    # Has children — show next level and update state
    _set_state(phone, company_id, _MenuState(path=new_path, conversation_id=conversation_id))
    logger.info(
        "[INFO] [menu] Navigated to level %d — phone: ...%s, path: %s",
        len(new_path),
        phone[-4:],
        breadcrumb,
    )
    return _format_level(kids), None


def invalidate_cache(company_id: int | None = None) -> None:
    """Force next call to reload menuConfig from the DB."""
    global _config_cache
    if company_id is not None:
        _config_cache.pop(company_id, None)
    else:
        _config_cache.clear()
