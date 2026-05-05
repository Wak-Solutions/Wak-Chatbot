"""_config.py — load and cache structured menuConfig from chatbot_config table per company."""

import json
import logging
import time as _time

import database

logger = logging.getLogger(__name__)

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
                "menuConfig loaded — company_id: %d, top-level items: %d",
                company_id,
                len(menu_items),
            )
            return menu_items
    except Exception as exc:
        logger.warning(
            "Could not load menuConfig — company_id: %d, error: %s",
            company_id,
            exc,
        )
    if cached:
        return cached[0]
    return []


def invalidate_cache(company_id: int | None = None) -> None:
    """Force next call to reload menuConfig from the DB."""
    global _config_cache
    if company_id is not None:
        _config_cache.pop(company_id, None)
    else:
        _config_cache.clear()
