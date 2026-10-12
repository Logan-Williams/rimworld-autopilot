"""Player-facing guidance shared by the GUI and autonomous director."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PRIORITIES = {
    "survival": 100,
    "food": 100,
    "construction": 60,
    "research": 55,
    "economy": 45,
    "defense": 70,
    "animals": 55,
    "diplomacy": 45,
    "ideology": 75,
    "expansion": 40,
    "development_pace": 50,
}
VISIBLE_PRIORITIES = ('development_pace', 'construction', 'research', 'economy',
                      'defense', 'animals', 'diplomacy', 'ideology', 'expansion')

DEFAULT_PREFERENCES: dict[str, Any] = {
    "schema_version": 3,
    "language": "ru",
    "victory_required": True,
    "technical_logging": False,
    "overlay": {
        "enabled": True,
        "compact": True,
        "max_options": 5,
    },
    "observer": {"enabled": False},
    "priorities": DEFAULT_PRIORITIES,
    "personal_note": "",
    "safety": {
        "avoid_unprovoked_attacks": False,
        "prefer_peaceful_trade": False,
        "protect_food_reserve": True,
    },
}


def preferences_path(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return base_dir / "autopilot-preferences.json"
    configured = os.environ.get("RIMWORLD_AUTOPILOT_PREFERENCES")
    if configured:
        return Path(configured)
    source_dir = Path(__file__).resolve().parent
    program_roots = [Path(value).resolve() for key in ("ProgramFiles", "ProgramFiles(x86)") if (value := os.environ.get(key))]
    if any(source_dir == root or root in source_dir.parents for root in program_roots):
        return Path(os.environ.get("LOCALAPPDATA", str(source_dir))) / "RimWorld Autopilot" / "autopilot-preferences.json"
    return source_dir / "autopilot-preferences.json"


def load_preferences(path: Path | None = None) -> dict[str, Any]:
    result = {
        **DEFAULT_PREFERENCES,
        "priorities": dict(DEFAULT_PRIORITIES),
        "safety": dict(DEFAULT_PREFERENCES["safety"]),
        "overlay": dict(DEFAULT_PREFERENCES["overlay"]),
        "observer": dict(DEFAULT_PREFERENCES["observer"]),
    }
    source = path or preferences_path()
    if path is None and not source.exists():
        legacy = source.with_name("laya-preferences.json")
        if legacy.exists():
            source = legacy
    try:
        loaded = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return result
    if not isinstance(loaded, dict):
        return result
    result.update({key: value for key, value in loaded.items() if key not in {"priorities", "safety", "overlay", "observer"}})
    if isinstance(loaded.get("priorities"), dict):
        for key in DEFAULT_PRIORITIES:
            try:
                result["priorities"][key] = max(0, min(100, int(loaded["priorities"].get(key, result["priorities"][key]))))
            except (TypeError, ValueError):
                pass
    if isinstance(loaded.get("safety"), dict):
        result["safety"].update({key: bool(value) for key, value in loaded["safety"].items() if key in result["safety"]})
    if isinstance(loaded.get("overlay"), dict):
        result["overlay"].update({
            "enabled": bool(loaded["overlay"].get("enabled", result["overlay"]["enabled"])),
            "compact": bool(loaded["overlay"].get("compact", result["overlay"]["compact"])),
        })
        try:
            result["overlay"]["max_options"] = max(3, min(8, int(loaded["overlay"].get("max_options", 5))))
        except (TypeError, ValueError):
            pass
    if isinstance(loaded.get("observer"), dict):
        result["observer"]["enabled"] = bool(loaded["observer"].get("enabled", False))
    result['priorities']['survival'] = result['priorities']['food'] = 100
    result["language"] = "en" if result.get("language") == "en" else "ru"
    result["technical_logging"] = bool(result.get("technical_logging"))
    result["victory_required"] = bool(result.get("victory_required"))
    result["personal_note"] = str(result.get("personal_note") or "")[:1200]
    return result


def save_preferences(data: dict[str, Any], path: Path | None = None) -> None:
    destination = path or preferences_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = load_preferences_from_value(data)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)


def load_preferences_from_value(data: dict[str, Any]) -> dict[str, Any]:
    result = {
        **DEFAULT_PREFERENCES,
        "priorities": dict(DEFAULT_PRIORITIES),
        "safety": dict(DEFAULT_PREFERENCES["safety"]),
        "overlay": dict(DEFAULT_PREFERENCES["overlay"]),
        "observer": dict(DEFAULT_PREFERENCES["observer"]),
    }
    if isinstance(data, dict):
        result.update({key: value for key, value in data.items() if key not in {"priorities", "safety", "overlay", "observer"}})
        for key in DEFAULT_PRIORITIES:
            try:
                result["priorities"][key] = max(0, min(100, int((data.get("priorities") or {}).get(key, result["priorities"][key]))))
            except (AttributeError, TypeError, ValueError):
                pass
        if isinstance(data.get("safety"), dict):
            result["safety"].update({key: bool(value) for key, value in data["safety"].items() if key in result["safety"]})
        if isinstance(data.get("overlay"), dict):
            result["overlay"].update({
                "enabled": bool(data["overlay"].get("enabled", result["overlay"]["enabled"])),
                "compact": bool(data["overlay"].get("compact", result["overlay"]["compact"])),
            })
            try:
                result["overlay"]["max_options"] = max(3, min(8, int(data["overlay"].get("max_options", 5))))
            except (TypeError, ValueError):
                pass
        if isinstance(data.get("observer"), dict):
            result["observer"]["enabled"] = bool(data["observer"].get("enabled", False))
    result['priorities']['survival'] = result['priorities']['food'] = 100
    result["language"] = "en" if result.get("language") == "en" else "ru"
    result["technical_logging"] = bool(result.get("technical_logging"))
    result["victory_required"] = bool(result.get("victory_required"))
    result["personal_note"] = str(result.get("personal_note") or "")[:1200]
    return result


def priority_key_for_action(action: str) -> str:
    name = str(action).lower()
    if any(token in name for token in ("ideology", "ritual", "temple", "altar", "precept", "convert")):
        return "ideology"
    if any(token in name for token in ("raid_to", "settlement", "outpost", "annex", "conquer")):
        return "expansion"
    if name == "inspirations_recruit":
        return "diplomacy"
    if name in {"build_passive_cooler", "build_room_campfire", "build_room_heater",
                "connect_room_heater_power",
                "prioritize_thermal_project"}:
        return "survival"
    if any(token in name for token in ("food", "cook", "growing", "harvest", "hunt", "freezer", "sowing")):
        return "food"
    if any(token in name for token in ("animal", "taming", "breed")):
        return "animals"
    if any(token in name for token in ("raid", "combat", "defense", "killbox", "turret", "mortar", "armament", "mechanoid")):
        return "defense"
    if any(token in name for token in ("research", "hitech", "fabrication", "workbench")):
        return "research"
    if any(token in name for token in ("income", "trade", "caravan", "prisoner_policy", "orbital")):
        return "economy"
    if any(token in name for token in ("build", "floor", "path", "architect", "stockpile", "cemetery", "crematorium")):
        return "construction"
    if any(token in name for token in ("quest", "rescue", "goodwill", "diplomacy")):
        return "diplomacy"
    return "survival"


def priority_for_action(action: str, preferences: dict[str, Any]) -> int:
    key = priority_key_for_action(action)
    if key in {'survival', 'food'} or any(token in action.lower() for token in
            ('medical', 'tend', 'feed', 'sleep', 'rest', 'rescue', 'fire', 'retreat', 'thermal',
             'emergency', 'combat', 'engage', 'civilian', 'stand_down')):
        return 100
    priorities = preferences.get('priorities') or {}
    weight = int(priorities.get(key, 50))
    pace = int(priorities.get('development_pace', 50))
    return max(0, min(95, round(weight * (0.6 + pace / 125))))


def filter_candidates(candidates: list[str], preferences: dict[str, Any]) -> list[str]:
    safety = preferences.get("safety") or {}
    priorities = preferences.get("priorities") or {}
    result = list(candidates)
    if safety.get("avoid_unprovoked_attacks"):
        result = [name for name in result if not name.startswith("raid_to:")]
    # A zero-expansion campaign must not offer a conquest action merely because
    # it is technically available.  The independent attack safety boundary
    # remains stricter whenever it is enabled.
    if int(priorities.get("expansion", 50)) <= 20:
        result = [name for name in result if not name.startswith("raid_to:")]
    return result or ["hold_survival"]


def model_context(preferences: dict[str, Any]) -> dict[str, Any]:
    priorities = dict(preferences.get("priorities") or {})
    expansion = int(priorities.get("expansion", 50))
    priorities.pop('autonomy', None)
    priorities['survival'] = priorities['food'] = 100
    pace = int(priorities.get('development_pace', 50))
    return {
        "priority_weights_0_to_100": priorities,
        "personal_guidance": str(preferences.get("personal_note") or ""),
        "victory_required": bool(preferences.get("victory_required")),
        "safety_preferences": dict(preferences.get("safety") or {}),
        "campaign_controls": {
            "ideology_priority": int(priorities.get("ideology", 50)),
            "expansion_posture": "peaceful consolidation" if expansion <= 35 else "measured influence" if expansion < 70 else "active expansion",
            "development_pace": 'cautious: finish existing projects before new optional work' if pace <= 35 else
                'balanced: develop within available workers and resources' if pace < 70 else
                'active: pursue feasible construction, research and expansion without displacing essential care',
            "mandatory_care": 'Always handle food, treatment, rest and immediate safety regardless of development pace. '
                'Routine orders must not interrupt sleep; life-threatening emergencies remain exceptions.',
            "hard_political_boundary": "Do not break treaties, select independence, declare war, pay tribute, or choose political letters without an explicit player instruction.",
        },
        "instruction": "Treat these as player preferences, not permission to violate feasibility, emergency or safety gates. A high expansion value never overrides the no-unprovoked-attacks safety boundary.",
    }
