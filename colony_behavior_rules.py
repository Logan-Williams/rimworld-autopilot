"""Player-owned behaviour invariants for Laya's feasible action frontier.

Rules express *what must be protected*, while the director and the learning
layer may choose *how* to achieve an ordinary goal.  This module has no client,
does not create action IDs, and therefore cannot bypass the native RimWorld
validation used by the director.
"""
from __future__ import annotations

import math
from typing import Any


BEHAVIOUR_CONTRACT = "colony_behavior_rules.v1"
DEFAULT_POLICY = {
    "prepared_meal_reserve_days": 2.0,
    "cold_weather_c": 5.0,
}

CARE_PREFIXES = ("rescue_", "tend_", "feed_", "eat_", "resilience_")
CARE_ACTIONS = {
    "hold_survival", "prioritize_doctor", "prioritize_rescue",
    "prioritize_firefighting", "fight_fire", "extinguish_fire",
    "open_blocked_food_path", "open_sealed_food_store", "unforbid_supplies",
    "prepare_emergency_medical_bed", "prepare_patient_bed",
}
COOKING_ACTIONS = {
    "configure_food_bills", "prioritize_cooking", "rebalance_cooking",
    "sustenance_food_batch", "sustenance_food_policy", "build_campfire",
}
SHELTER_ACTIONS = {
    "build_starter_base", "resilience_shelter", "prioritize_construction_project",
    "prioritize_construction", "build_room_campfire", "build_room_heater",
    "connect_room_heater_power", "prioritize_thermal_project", "refuel_building",
}
WARMTH_ACTIONS = {
    "build_room_campfire", "build_room_heater", "connect_room_heater_power",
    "prioritize_thermal_project", "refuel_building", "resilience_temperature",
}

# The current collector and executor can heat rooms, but do not expose enough
# evidence to make a safe clothing order: worn apparel and insulation, loose
# apparel condition/insulation, reachability, reservations and an executable
# per-pawn wear choice.  Keep this declaration explicit so a mod action whose
# name merely looks plausible cannot turn that gap into an unsafe command.
CLOTHING_EVIDENCE_GAP = (
    "worn_apparel_insulation", "loose_apparel_condition_and_insulation",
    "wearable_reachable_unreserved_choice",
)


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return value if math.isfinite(value) else fallback


def normalize_policy(value: Any) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    return {
        "prepared_meal_reserve_days": max(0.5, min(5.0, _number(
            source.get("prepared_meal_reserve_days"), DEFAULT_POLICY["prepared_meal_reserve_days"]))),
        "cold_weather_c": max(-30.0, min(15.0, _number(
            source.get("cold_weather_c"), DEFAULT_POLICY["cold_weather_c"]))),
    }


def _living(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [pawn for pawn in snapshot.get("colonists") or []
            if isinstance(pawn, dict) and not pawn.get("dead") and not pawn.get("is_dead")]


def _roofed_sleepers(snapshot: dict[str, Any]) -> int:
    development = snapshot.get("development") or {}
    explicit = development.get("roofed_sleeping_places")
    if explicit is not None:
        return max(0, int(_number(explicit)))
    return sum(
        len(room.get("contained_beds_ids") or [])
        for room in development.get("rooms") or []
        if isinstance(room, dict) and not room.get("touches_map_edge")
        and int(_number(room.get("open_roof_count"))) == 0
    )


def _cold_weather(snapshot: dict[str, Any], policy: dict[str, float]) -> bool:
    weather = (snapshot.get("development") or {}).get("weather") or {}
    temperatures = [weather.get("temperature"), weather.get("outside_c")]
    temperatures.extend(weather.get("next_twelfth_average_temperatures") or [])
    known = [_number(value, float("nan")) for value in temperatures]
    known = [value for value in known if math.isfinite(value)]
    return bool(known and min(known) <= policy["cold_weather_c"])


def _protected(action: str) -> bool:
    name = str(action)
    return name in CARE_ACTIONS or name.startswith(CARE_PREFIXES)


def _native_emergency(snapshot: dict[str, Any], candidates: list[str]) -> bool:
    development = snapshot.get("development") or {}
    if any(_protected(action) for action in candidates):
        return True
    if development.get("food_emergency_context") or development.get("blocked_food_emergency"):
        return True
    if development.get("cold_start_focus") or development.get("heatstroke_focus"):
        return True
    return any(_number(pawn.get("hunger"), 1.0) < 0.10 for pawn in _living(snapshot))


def _frontier(candidates: list[str], allowed: set[str]) -> list[str]:
    """Return only action IDs supplied by this cycle's native frontier."""
    return [action for action in candidates if action in allowed]


def _directive(identifier: str, state: str, *, trigger_evidence: dict[str, Any],
               allowed_actions: list[str], forbidden_actions: list[str],
               rationale: str, missing_evidence: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return an audit-friendly policy result without creating any command."""
    return {
        "id": identifier,
        "state": state,
        "trigger_evidence": trigger_evidence,
        "hard_guards": ["native_frontier_only", "no_emergency_override"],
        "allowed_actions": allowed_actions,
        "forbidden_actions": forbidden_actions,
        "missing_evidence": list(missing_evidence),
        "rationale": rationale,
    }


def apply(snapshot: dict[str, Any], candidates: list[str], *,
          policy: dict[str, Any] | None = None) -> tuple[list[str], dict[str, Any]]:
    """Apply invariant goals without deciding the exact implementation.

    A rule may reduce the current feasible candidates to a goal family.  It
    never restores a backed-off action or fabricates a missing native clothing,
    diet, construction, or medical command.
    """
    current = list(dict.fromkeys(str(action) for action in candidates))
    configuration = normalize_policy(policy)
    audit: dict[str, Any] = {
        "contract": BEHAVIOUR_CONTRACT,
        "phase": "ordinary",
        "goals": [],
        "blockers": [],
        "directives": [],
        "policy": configuration,
    }
    if not current or _native_emergency(snapshot, current):
        audit["phase"] = "native_emergency"
        return current, audit

    people = _living(snapshot)
    shelter_needed = bool(people and _roofed_sleepers(snapshot) < len(people))
    if shelter_needed:
        audit["goals"].append("shelter_before_optional_work")
        focused = _frontier(current, SHELTER_ACTIONS)
        if focused:
            audit["phase"] = "shelter"
            audit["directives"].append(_directive(
                "shelter.before_optional_work", "active",
                trigger_evidence={"roofed_sleepers": _roofed_sleepers(snapshot), "living": len(people)},
                allowed_actions=focused, forbidden_actions=[],
                rationale="A roofed sleeping place is missing; use only an already feasible shelter action.",
            ))
            return focused, audit
        audit["blockers"].append("shelter_action_unavailable")
        audit["directives"].append(_directive(
            "shelter.before_optional_work", "blocked",
            trigger_evidence={"roofed_sleepers": _roofed_sleepers(snapshot), "living": len(people)},
            allowed_actions=[], forbidden_actions=[],
            rationale="No feasible shelter action was offered by the native frontier.",
        ))

    if _cold_weather(snapshot, configuration):
        audit["goals"].append("winter_protection")
        warmth = _frontier(current, WARMTH_ACTIONS)
        audit["directives"].append(_directive(
            "clothing.cold_readiness", "blocked",
            trigger_evidence={"weather_at_or_below_c": configuration["cold_weather_c"]},
            allowed_actions=[], forbidden_actions=[],
            rationale="The current RIMAPI snapshot cannot prove a safe per-pawn clothing choice.",
            missing_evidence=CLOTHING_EVIDENCE_GAP,
        ))
        if warmth:
            audit["phase"] = "winter_protection"
            audit["directives"].append(_directive(
                "room_warmth.cold_readiness", "active",
                trigger_evidence={"weather_at_or_below_c": configuration["cold_weather_c"]},
                allowed_actions=warmth, forbidden_actions=[],
                rationale="Use a currently feasible native heat action while clothing remains unverifiable.",
            ))
            return warmth, audit
        audit["blockers"].append("warm_protection_action_unavailable")

    resources = (snapshot.get("map") or {}).get("resources") or {}
    raw_food = _number(resources.get("raw_food"))
    prepared_meals = _number(resources.get("meals"))
    meal_target = math.ceil(len(people) * 1.6 * configuration["prepared_meal_reserve_days"] / 0.9)
    audit["meal_target"] = max(1, meal_target)
    if raw_food > 0 and prepared_meals < audit["meal_target"]:
        audit["goals"].append("prepared_food_before_raw_food_preference")
        focused = _frontier(current, COOKING_ACTIONS)
        if focused:
            audit["phase"] = "prepared_food"
            audit["directives"].append(_directive(
                "food.prepared_reserve", "active",
                trigger_evidence={"raw_food": raw_food, "prepared_meals": prepared_meals,
                                  "meal_target": audit["meal_target"]},
                allowed_actions=focused, forbidden_actions=[],
                rationale="Healthy colonists should restore the prepared-meal reserve through a feasible cooking action.",
            ))
            return focused, audit
        # No current native diet/cooking action means this module must report
        # the gap, never pretend it successfully forbade raw food.
        audit["blockers"].append("prepared_food_action_unavailable")
        audit["directives"].append(_directive(
            "food.prepared_reserve", "blocked",
            trigger_evidence={"raw_food": raw_food, "prepared_meals": prepared_meals,
                              "meal_target": audit["meal_target"]},
            allowed_actions=[], forbidden_actions=[],
            rationale="No feasible cooking or diet-policy action was offered by the native frontier.",
        ))

    return current, audit
