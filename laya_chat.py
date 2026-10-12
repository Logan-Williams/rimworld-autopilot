"""Safe player-chat directives for the Laya control centre.

This module intentionally does *not* call RimWorld, an LLM, or an MCP server.
It translates a short player message into a small set of known, reviewable
goals.  The director may consider those goals only when the message is bound
to the currently observed map and its usual safety gates still allow an
action.  Free-form player text never enters the model context.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


CHAT_SCHEMA_VERSION = 1
MAX_MESSAGE_LENGTH = 480
MAX_HISTORY_ENTRIES = 24
MAX_DIRECTIVES = 8

DIRECTIVES: dict[str, dict[str, Any]] = {
    "thermal_safety": {
        "keywords": ("холод", "замерз", "мёрз", "мерз", "согре", "тепл", "тёпл", "одеж", "одеть", "одень", "cold", "freez", "warm", "cloth", "dress"),
        "model_goal": "Protect colonists from cold through observed, feasible shelter and room warmth actions.",
        "reply": (
            "Поняла приоритет: защита от холода. Я передам Лее цель проверить укрытие и тепло в помещениях. "
            "Одежду пока нельзя назначать автоматически: нет подтверждённых данных о вещах, утеплении, доступности и безопасном действии надеть вещь."
        ),
        "blockers": [
            "worn_apparel_insulation",
            "loose_apparel_condition_and_insulation",
            "wearable_reachable_unreserved_choice",
        ],
    },
    "prepared_food": {
        "keywords": ("еда", "голод", "готов", "кухн", "сыро", "сырой", "паёк", "паек", "готовить", "food", "hungr", "cook", "raw", "meal"),
        "model_goal": "Restore a prepared-food reserve when the current observation offers a safe cooking path.",
        "reply": "Поняла приоритет: готовая еда и безопасный запас. Лея будет предпочитать доступные действия готовки, но не отменит лечение, пожар, спасение и срочную еду.",
        "blockers": [],
    },
    "shelter_first": {
        "keywords": ("дом", "укрыт", "крыша", "жиль", "спальн", "кровать", "home", "shelter", "roof", "bedroom", "sleeping"),
        "model_goal": "Secure roofed sleeping capacity before discretionary colony development.",
        "reply": "Поняла приоритет: сначала безопасное жильё и спальные места. Лея сможет выбрать только уже доступный в игре вариант строительства.",
        "blockers": [],
    },
    "peaceful_trade": {
        "keywords": ("торгов", "диплом", "мирн", "мир", "не воюй", "не напад", "переговор", "trad", "diplom", "peace", "negotiat"),
        "model_goal": "Prefer peaceful trade and diplomacy; do not create an unprovoked attack path.",
        "reply": "Поняла курс: мирная торговля и дипломатия. Это предпочтение не создаёт нападений и не меняет политические письма без отдельного решения игрока.",
        "blockers": [],
    },
    "hold_and_explain": {
        "keywords": ("останов", "стоп", "подожди", "не делай", "отмени", "пауза", "stop", "wait", "cancel", "pause", "do not"),
        "model_goal": "Hold discretionary development and explain the next safe decision boundary.",
        "reply": "Поняла: передать Лее предпочтение не начинать необязательное развитие и сначала объяснить следующий выбор. Экстренная помощь, пожар, лечение, еда и спасение не отключаются этой просьбой.",
        "blockers": [],
    },
}

_DIRECTIVE_ORDER = tuple(DIRECTIVES)


def _bounded_text(value: Any, limit: int = MAX_MESSAGE_LENGTH) -> str:
    return " ".join(str(value or "").split())[:limit]


def _map_fingerprint(value: Any) -> str | None:
    result = _bounded_text(value, 160)
    return result or None


def _game_tick(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def map_fingerprint(map_info: Any) -> str | None:
    """Match the GUI/director map key without importing either layer."""
    if not isinstance(map_info, dict):
        return None
    values = [map_info.get(field) for field in ("seed", "tile_id", "id")]
    if all(value is None for value in values):
        return None
    return ":".join(str(value) if value is not None else "unknown" for value in values)


def classify_message(text: Any) -> list[str]:
    """Return every known goal named by a bounded player message.

    This is deliberately deterministic.  It cannot follow a prompt injection,
    infer a game endpoint, or claim that an unknown sentence was executed.
    """
    normalized = _bounded_text(text).casefold()
    if not normalized:
        return []
    words = tuple(re.findall(r"\w+", normalized))

    def mentions(keyword: str) -> bool:
        if " " in keyword:
            return keyword in normalized
        return any(word.startswith(keyword) for word in words)

    return [identifier for identifier in _DIRECTIVE_ORDER
            if any(mentions(keyword) for keyword in DIRECTIVES[identifier]["keywords"])]


def normalize_directives(value: Any) -> list[dict[str, Any]]:
    """Keep only bounded, known directive records from persisted preferences."""
    rows = value if isinstance(value, list) else []
    newest_by_id: dict[str, dict[str, Any]] = {}
    for row in rows[-MAX_DIRECTIVES:]:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("id") or "")
        if identifier not in DIRECTIVES:
            continue
        fingerprint = _map_fingerprint(row.get("map_fingerprint"))
        newest_by_id[identifier] = {
            "id": identifier,
            "source_text": _bounded_text(row.get("source_text")),
            "created_at": _bounded_text(row.get("created_at"), 48),
            "map_fingerprint": fingerprint,
            "created_game_tick": _game_tick(row.get("created_game_tick")),
            "state": "active" if fingerprint else "proposed",
        }
    return list(newest_by_id.values())[-MAX_DIRECTIVES:]


def normalize_history(value: Any) -> list[dict[str, Any]]:
    """Bound local transcript records; the transcript is never model input."""
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for row in rows[-MAX_HISTORY_ENTRIES:]:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user", "laya"}:
            continue
        text = _bounded_text(row.get("text"))
        if not text:
            continue
        result.append({
            "role": role,
            "text": text,
            "created_at": _bounded_text(row.get("created_at"), 48),
            "directive_ids": [str(identifier) for identifier in (row.get("directive_ids") or [])
                              if str(identifier) in DIRECTIVES][:len(DIRECTIVES)],
            "state": str(row.get("state") or "")[:24],
        })
    return result


def active_directives(value: Any, *, current_map_fingerprint: Any,
                      current_game_tick: Any) -> list[dict[str, str]]:
    """Return canonical goals applicable to this exact non-rewound map only."""
    current_map = _map_fingerprint(current_map_fingerprint)
    current_tick = _game_tick(current_game_tick)
    if not current_map:
        return []
    active: list[dict[str, str]] = []
    for directive in normalize_directives(value):
        if directive["map_fingerprint"] != current_map:
            continue
        created_tick = directive["created_game_tick"]
        if current_tick is not None and created_tick is not None and current_tick < created_tick:
            continue
        spec = DIRECTIVES[directive["id"]]
        active.append({"id": directive["id"], "goal": str(spec["model_goal"])})
    return active


def submit_message(text: Any, *, map_fingerprint: Any = None,
                   game_tick: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Compile one player message to non-executable directives and UI entries."""
    source_text = _bounded_text(text)
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    directive_ids = classify_message(source_text)
    fingerprint = _map_fingerprint(map_fingerprint)
    tick = _game_tick(game_tick)
    if not source_text:
        return {"accepted": False, "directives": [], "history": [],
                "reply": "Напишите, какую цель вы хотите задать Лее.", "state": "unsupported"}
    if not directive_ids:
        reply = (
            "Я пока понимаю только безопасные цели: тепло, готовая еда, жильё, мирная торговля и остановка необязательных работ. "
            "Сообщение сохранено только в чате и не стало игровой командой."
        )
        return {
            "accepted": False,
            "directives": [],
            "history": [
                {"role": "user", "text": source_text, "created_at": timestamp, "directive_ids": [], "state": "unsupported"},
                {"role": "laya", "text": reply, "created_at": timestamp, "directive_ids": [], "state": "unsupported"},
            ],
            "reply": reply,
            "state": "unsupported",
        }

    state = "active" if fingerprint else "proposed"
    directives = [{
        "id": identifier,
        "source_text": source_text,
        "created_at": timestamp,
        "map_fingerprint": fingerprint,
        "created_game_tick": tick,
        "state": state,
    } for identifier in directive_ids]
    scope = (
        " Цель привязана к текущей карте и будет считаться только в следующем безопасном цикле Laya."
        if fingerprint else
        " Игра сейчас не подтвердила карту: цель сохранена как предложение и не будет применена автоматически."
    )
    reply = "\n\n".join(DIRECTIVES[identifier]["reply"] for identifier in directive_ids) + scope + " Команда в RimWorld не отправлялась."
    return {
        "accepted": True,
        "directives": directives,
        "history": [
            {"role": "user", "text": source_text, "created_at": timestamp, "directive_ids": directive_ids, "state": state},
            {"role": "laya", "text": reply, "created_at": timestamp, "directive_ids": directive_ids, "state": "not_executed"},
        ],
        "reply": reply,
        "state": state,
    }


def merge_directives(existing: Any, additions: Any) -> list[dict[str, Any]]:
    """Replace an older version of the same goal while retaining other goals."""
    merged = {row["id"]: row for row in normalize_directives(existing)}
    for row in normalize_directives(additions):
        merged[row["id"]] = row
    return list(merged.values())[-MAX_DIRECTIVES:]


def merge_history(existing: Any, additions: Any) -> list[dict[str, Any]]:
    return normalize_history([*normalize_history(existing), *normalize_history(additions)])[-MAX_HISTORY_ENTRIES:]
