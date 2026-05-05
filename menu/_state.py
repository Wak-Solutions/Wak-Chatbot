"""_state.py — in-memory navigation state keyed by (phone, company_id) with LRU eviction."""

from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class _MenuState:
    # 0-based index path through the tree, e.g. [0, 1] = first item, second sub-item
    path: list[int] = field(default_factory=list)
    # Scopes state to the active 24-hour session; resets automatically when session changes
    conversation_id: str = ""


# (customer_phone, company_id) → _MenuState; capped at _MAX_STATES entries (LRU eviction).
_MAX_STATES = 10_000
_states: OrderedDict = OrderedDict()


def _get_state(phone: str, company_id: int, conversation_id: str) -> _MenuState | None:
    key = (phone, company_id)
    state = _states.get(key)
    if state is None or state.conversation_id != conversation_id:
        return None
    _states.move_to_end(key)
    return state


def _set_state(phone: str, company_id: int, state: _MenuState) -> None:
    key = (phone, company_id)
    _states[key] = state
    _states.move_to_end(key)
    if len(_states) > _MAX_STATES:
        _states.popitem(last=False)


def clear_state(phone: str, company_id: int) -> None:
    _states.pop((phone, company_id), None)
