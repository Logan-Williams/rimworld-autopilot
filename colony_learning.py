"""Evidence-gated reward memory for Laya's existing safe action frontier.

This module never trains model weights, creates actions, or treats a command as
completed.  It only records a *measured correlation* between one accepted
command and the next observation.  A preference becomes usable only after
repeated matching observations pass the promotion gate.  Life-safety actions
are never re-ordered by this module.
"""
from __future__ import annotations

import json
from typing import Any


LEARNING_CONTRACT = "laya_reward_learning.v1"
MAX_EPISODES = 96
MAX_PROFILES = 96
MIN_SAMPLES = 3
MIN_NET_REWARD = 6
NORMAL_DEVELOPMENT_SCOPE = "development_normal_path"
MAX_OBSERVATION_TICKS = 30000

# Learning begins with a deliberately small whitelist.  These are ordinary
# development alternatives, never rescue, food, fire, thermal or expedition
# work.  Additions require an executor review and a director-level regression.
NORMAL_DEVELOPMENT_ACTIONS = {
    "prioritize_construction", "prioritize_construction_project",
    "build_research_bench", "select_research", "repair_research_bench",
    "upgrade_workbench", "plan_architecture", "repair_architecture",
}

# These actions must retain the controller's original order.  The learning
# memory is deliberately an adviser to a filtered frontier, never an emergency
# override.
PROTECTED_PREFIXES = ("rescue_", "tend_", "feed_", "eat_", "resilience_", "society_")
PROTECTED_ACTIONS = {
    "hold_survival", "prepare_emergency_medical_bed", "prioritize_doctor",
    "prioritize_rescue", "prioritize_firefighting", "extinguish_fire", "fight_fire",
    "prepare_patient_bed", "care_for_injured_animal", "rescue_downed_animal",
    "feed_hungry_animal", "eat_available_meal", "open_blocked_food_path",
    "open_sealed_food_store", "unforbid_supplies", "harvest_local_plants",
    "harvest_food_crops_early",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _measurement_number(value: Any) -> float | None:
    """Use collection cardinality for RIMAPI list-valued measurements."""
    if isinstance(value, (list, tuple, set, dict)):
        return float(len(value))
    return _number(value)


def _delta(changes: dict[str, Any], name: str) -> float | None:
    change = changes.get(name)
    if not isinstance(change, dict):
        return None
    before = _measurement_number(change.get("before"))
    after = _measurement_number(change.get("after"))
    if before is None or after is None:
        return None
    return after - before


def action_domain(action: str) -> str:
    """Return the measured objective that an existing action is meant to help."""
    name = str(action or "")
    if name.startswith(("rescue_", "tend_", "feed_")) or name in {
            "prioritize_doctor", "prioritize_rescue", "prepare_emergency_medical_bed"}:
        return "care"
    if name.startswith(("harvest_", "sustenance_")) or name in {
            "prioritize_cooking", "configure_food_bills", "rebalance_cooking",
            "build_campfire", "connect_power_consumer", "prioritize_hunting",
            "designate_safe_hunting", "prioritize_growing", "open_blocked_food_path"}:
        return "food"
    if name in {"equip_colonists", "build_killbox", "build_fallback_defense",
                "build_turret_defense", "build_mortar_post", "build_firefoam_defense"}:
        return "defense"
    if name.startswith(("build_", "finish_", "install_", "floor_")) or name in {
            "prioritize_construction", "prioritize_construction_project",
            "replace_blocked_shell_material", "repair_architecture"}:
        return "construction"
    if name.startswith("prioritize_research") or "research" in name:
        return "research"
    return "other"


def scenario_signature(snapshot: dict[str, Any]) -> str:
    """Use coarse current facts only; no pawn names, positions or free text."""
    dev = snapshot.get("development") or {}
    resources = (snapshot.get("map") or {}).get("resources") or {}
    food = dev.get("food_budget") or dev.get("sustenance") or {}
    progress = dev.get("housing_progress") or {}
    power = dev.get("power_info") or {}
    colonists = snapshot.get("colonists") or []
    enemies = (snapshot.get("map") or {}).get("enemies") or []
    values = {
        "care": "downed" if any(bool(row.get("downed")) for row in colonists if isinstance(row, dict)) else "stable",
        "construction": "pending" if dev.get("construction_projects") else "none",
        "food": str(food.get("state") or "unknown"),
        "housing": str(progress.get("phase") or "unknown"),
        "power": "unpowered" if dev.get("cooking_power_recovery") or power.get("current_power") == 0 else "available",
        "threat": "present" if enemies else "none",
        "stock": "empty" if resources.get("meals") == 0 and resources.get("nutrition") == 0 else "known",
    }
    return "|".join(f"{key}={values[key]}" for key in sorted(values))


def learning_scope(snapshot: dict[str, Any], candidates: list[str], *, expedition: bool = False) -> str:
    """Return the one scope in which a ranking lesson is allowed.

    This is an explicit whitelist rather than a growing blacklist.  A new
    action is ineligible until its executor and observable outcome have been
    reviewed, so an unfamiliar mod action cannot accidentally become training
    material.
    """
    development = snapshot.get("development") or {}
    if expedition:
        return "expedition"
    if not candidates:
        return "no_candidates"
    if (snapshot.get("map") or {}).get("enemies") or snapshot.get("enemies"):
        return "hostiles_present"
    fire = development.get("fire_situation") or {}
    if any(bool(fire.get(key)) for key in ("home_area_fires", "home_fire_count", "home_fires")):
        return "home_fire"
    if any(bool(pawn.get("downed")) for pawn in snapshot.get("colonists") or [] if isinstance(pawn, dict)):
        return "downed_colonist"
    if any(bool(development.get(key)) for key in (
            "food_emergency_context", "blocked_food_emergency", "cooking_gap_urgent",
            "cold_start_focus", "heatstroke_focus")):
        return "survival_or_thermal_focus"
    heat_threat = development.get("heat_threat") or {}
    cold_threat = development.get("cold_threat") or {}
    if heat_threat.get("patients") or cold_threat.get("patients"):
        return "thermal_patients"
    if any(protected(action) for action in candidates):
        return "protected_action_present"
    if not set(candidates).issubset(NORMAL_DEVELOPMENT_ACTIONS):
        return "action_not_whitelisted"
    return NORMAL_DEVELOPMENT_SCOPE


def _measurements(snapshot: dict[str, Any]) -> dict[str, Any]:
    """A compact, non-identifying observation used only for correlation."""
    development = snapshot.get("development") or {}
    resources = (snapshot.get("map") or {}).get("resources") or {}
    colonists = [row for row in snapshot.get("colonists") or [] if isinstance(row, dict)]
    return {
        "colonists_on_map": len(colonists),
        "downed": sum(bool(row.get("downed")) for row in colonists),
        "meals": resources.get("meals"),
        "nutrition": resources.get("nutrition"),
        "construction_projects": len(development.get("construction_projects") or []),
        "finished_research": len(development.get("finished_research") or []),
        "threats": len((snapshot.get("map") or {}).get("enemies") or []),
    }


def _pending_feedback(snapshot: dict[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    after = _measurements(snapshot)
    before = pending.get("measurements") if isinstance(pending.get("measurements"), dict) else {}
    changes = {
        key: {"before": value, "after": after.get(key)}
        for key, value in before.items()
        if value is not None and after.get(key) is not None and value != after[key]
    }
    return {
        "action": str(pending.get("action") or ""),
        "command": "accepted",
        "status": "observed_changes" if changes else "no_measured_change",
        "changes": changes,
        "causation": "not_established",
    }


def _empty_memory() -> dict[str, Any]:
    return {"contract": LEARNING_CONTRACT, "episodes": [], "profiles": {}}


def _memory(map_state: dict[str, Any]) -> dict[str, Any]:
    value = map_state.get("learning")
    if not isinstance(value, dict) or value.get("contract") != LEARNING_CONTRACT:
        value = _empty_memory()
        map_state["learning"] = value
    value.setdefault("episodes", [])
    value.setdefault("profiles", {})
    return value


def stage_decision(snapshot: dict[str, Any], map_state: dict[str, Any], action: str,
                   candidates: list[str], *, scope: str) -> dict[str, Any]:
    """Save the pre-command situation needed for a later, non-causal lesson."""
    if scope != NORMAL_DEVELOPMENT_SCOPE:
        return {"status": "scope_not_eligible", "contract": LEARNING_CONTRACT,
                "scope": str(scope)}
    memory = _memory(map_state)
    pending = memory.get("pending_decision")
    if isinstance(pending, dict):
        # The same paused game tick can run the director more than once.  Keep
        # the first pre-action observation until it has a terminal outcome;
        # replacing it would corrupt the later lesson's provenance.
        return {"status": "pending_feedback", "contract": LEARNING_CONTRACT,
                "action": str(pending.get("action") or "")}
    staged = {
        "action": str(action),
        "candidate_count": len(candidates),
        "scope": scope,
        "signature": scenario_signature(snapshot),
        "measurements": _measurements(snapshot),
        "tick": int((snapshot.get("game") or {}).get("tick") or 0),
    }
    memory["pending_decision"] = staged
    return {"status": "staged", "contract": LEARNING_CONTRACT, **staged}


def score_feedback(feedback: dict[str, Any], signature: str) -> dict[str, Any]:
    """Turn one observed outcome into an auditable reward or penalty.

    The value is evidence for a future ranking heuristic, not proof the action
    caused the change.  Rejected/unfinished commands receive no reward or
    penalty because they did not become a valid behavioural example.
    """
    action = str(feedback.get("action") or "")
    episode = {
        "contract": LEARNING_CONTRACT,
        "action": action,
        "domain": action_domain(action),
        "signature": signature,
        "command": str(feedback.get("command") or "unconfirmed"),
        "status": str(feedback.get("status") or "unknown"),
        "causation": "not_established",
        "reward": 0,
        "penalties": [],
        "rewards": [],
        "verdict": "unscored",
    }
    if episode["command"] != "accepted":
        episode["verdict"] = "not_applied"
        return episode
    if episode["status"] != "observed_changes":
        episode["verdict"] = "awaiting_evidence" if episode["status"] == "awaiting_game_progress" else "no_measured_change"
        return episode

    changes = feedback.get("changes") if isinstance(feedback.get("changes"), dict) else {}
    reward = 0
    downed = _delta(changes, "downed")
    threats = _delta(changes, "threats")
    colonists = _delta(changes, "colonists_on_map")
    if downed is not None and downed > 0:
        penalty = min(30, int(downed) * 12)
        reward -= penalty
        episode["penalties"].append(f"downed_increased:{int(downed)}")
    if threats is not None and threats > 0:
        penalty = min(24, int(threats) * 8)
        reward -= penalty
        episode["penalties"].append(f"threats_increased:{int(threats)}")
    if colonists is not None and colonists < 0:
        penalty = min(40, int(-colonists) * 20)
        reward -= penalty
        episode["penalties"].append(f"colonists_missing:{int(-colonists)}")

    domain = episode["domain"]
    if domain == "food":
        meals = _delta(changes, "meals")
        nutrition = _delta(changes, "nutrition")
        if (meals is not None and meals > 0) or (nutrition is not None and nutrition > 0):
            reward += 3
            episode["rewards"].append("food_stock_increased")
    elif domain == "care" and downed is not None and downed < 0:
        reward += 6
        episode["rewards"].append("downed_reduced")
    elif domain == "construction":
        projects = _delta(changes, "construction_projects")
        if projects is not None and projects < 0:
            reward += 3
            episode["rewards"].append("construction_projects_reduced")
    elif domain == "research":
        finished = _delta(changes, "finished_research")
        if finished is not None and finished > 0:
            reward += 3
            episode["rewards"].append("research_completed")
    elif domain == "defense" and threats is not None and threats < 0:
        reward += 4
        episode["rewards"].append("threats_reduced")

    episode["reward"] = reward
    if episode["penalties"]:
        episode["verdict"] = "penalty"
    elif episode["rewards"]:
        episode["verdict"] = "reward"
    else:
        episode["verdict"] = "neutral"
    return episode


def _profile(memory: dict[str, Any], signature: str, action: str) -> dict[str, Any]:
    key = json.dumps([signature, action], ensure_ascii=True, separators=(",", ":"))
    profiles = memory["profiles"]
    profile = profiles.get(key)
    if not isinstance(profile, dict):
        profile = {"signature": signature, "action": action, "observations": 0,
                   "reward_total": 0, "rewarded": 0, "penalized": 0,
                   "safety_regressions": 0, "active": False}
        profiles[key] = profile
    return profile


def _refresh_profile(profile: dict[str, Any]) -> None:
    profile["active"] = bool(
        profile["observations"] >= MIN_SAMPLES
        and profile["reward_total"] >= MIN_NET_REWARD
        and profile["rewarded"] >= MIN_SAMPLES
        and profile["penalized"] == 0
        and profile["safety_regressions"] == 0
    )


def reconcile(snapshot: dict[str, Any], map_state: dict[str, Any]) -> dict[str, Any]:
    """Consume one outcome feedback record once and update bounded evidence."""
    memory = _memory(map_state)
    feedback = (snapshot.get("development") or {}).get("outcome_feedback") or {}
    if not isinstance(feedback, dict) or not feedback:
        return {"status": "no_feedback", "contract": LEARNING_CONTRACT}
    if feedback.get("status") == "timeline_reset":
        memory.clear()
        memory.update(_empty_memory())
        memory["last_reset"] = "timeline_reset"
        return {"status": "timeline_reset", "contract": LEARNING_CONTRACT}
    pending = memory.get("pending_decision")
    if not isinstance(pending, dict) or pending.get("action") != feedback.get("action"):
        if not isinstance(pending, dict):
            return {"status": "decision_context_missing", "contract": LEARNING_CONTRACT}
    if pending.get("scope") != NORMAL_DEVELOPMENT_SCOPE:
        return {"status": "scope_not_eligible", "contract": LEARNING_CONTRACT,
                "scope": str(pending.get("scope") or "")}
    # The outcome observer emits this state in the same game tick as the
    # command.  Keep the pending decision so a later observation can become a
    # lesson; consuming it here would silently prevent all live learning.
    if feedback.get("status") == "awaiting_game_progress":
        return {"status": "awaiting_feedback", "contract": LEARNING_CONTRACT,
                "action": str(pending.get("action") or "")}
    observation_tick = int((snapshot.get("game") or {}).get("tick") or 0)
    elapsed_ticks = max(0, observation_tick - int(pending.get("tick") or 0))
    feedback_command_tick = feedback.get("command_tick")
    same_staged_command = (
        feedback.get("action") == pending.get("action")
        and _number(feedback_command_tick) == float(int(pending.get("tick") or 0))
    )
    if same_staged_command and feedback.get("command") != "accepted":
        terminal_feedback = feedback
    else:
        terminal_feedback = _pending_feedback(snapshot, pending)
        if (terminal_feedback["status"] == "no_measured_change"
                and elapsed_ticks < MAX_OBSERVATION_TICKS):
            return {"status": "awaiting_effect", "contract": LEARNING_CONTRACT,
                    "action": str(pending.get("action") or ""),
                    "elapsed_ticks": elapsed_ticks}
    memory.pop("pending_decision", None)
    # A later director command can be the outcome observer's most recent
    # action.  The lesson still belongs to the preserved pending decision.
    lesson_key = f"{pending.get('tick', 0)}:{observation_tick}:{pending.get('action', '')}"
    if memory.get("last_lesson_key") == lesson_key:
        return {"status": "already_reconciled", "contract": LEARNING_CONTRACT}
    episode = score_feedback(terminal_feedback, str(pending["signature"]))
    episode["scope"] = NORMAL_DEVELOPMENT_SCOPE
    episode["decision_tick"] = pending["tick"]
    episode["observation_tick"] = observation_tick
    memory["last_lesson_key"] = lesson_key
    if episode["verdict"] in {"reward", "penalty", "neutral"}:
        profile = _profile(memory, episode["signature"], episode["action"])
        profile["observations"] += 1
        profile["reward_total"] += int(episode["reward"])
        if episode["verdict"] == "reward":
            profile["rewarded"] += 1
        if episode["verdict"] == "penalty":
            profile["penalized"] += 1
        if any(item.startswith(("downed_increased", "threats_increased", "colonists_missing"))
               for item in episode["penalties"]):
            profile["safety_regressions"] += 1
        _refresh_profile(profile)
        episode["profile_active"] = profile["active"]
    episodes = memory["episodes"]
    episodes.append(episode)
    del episodes[:-MAX_EPISODES]
    profiles = memory["profiles"]
    if len(profiles) > MAX_PROFILES:
        for key in sorted(profiles)[:-MAX_PROFILES]:
            profiles.pop(key, None)
    return {"status": "recorded", "contract": LEARNING_CONTRACT, "episode": episode}


def protected(action: str) -> bool:
    return str(action).startswith(PROTECTED_PREFIXES) or str(action) in PROTECTED_ACTIONS


def rank_candidates(snapshot: dict[str, Any], map_state: dict[str, Any], candidates: list[str], *,
                    scope: str) -> tuple[list[str], dict[str, Any]]:
    """Reorder only current non-emergency candidates with promoted evidence.

    The returned list always contains exactly the supplied candidate IDs.  A
    caller may ignore it; this function has no game side effects.
    """
    original = list(candidates)
    evidence = {"contract": LEARNING_CONTRACT, "signature": scenario_signature(snapshot),
                "applied": False, "reason": "no_promoted_match", "profiles": []}
    if scope != NORMAL_DEVELOPMENT_SCOPE:
        evidence["reason"] = "scope_not_eligible"
        evidence["scope"] = str(scope)
        return original, evidence
    if any(protected(action) for action in original):
        evidence["reason"] = "protected_action_present"
        return original, evidence
    profiles = _memory(map_state)["profiles"]
    scored: dict[str, int] = {}
    for profile in profiles.values():
        if not isinstance(profile, dict) or not profile.get("active"):
            continue
        if profile.get("signature") != evidence["signature"]:
            continue
        action = str(profile.get("action") or "")
        if action not in original:
            continue
        scored[action] = int(profile.get("reward_total") or 0)
        evidence["profiles"].append({"action": action, "reward_total": scored[action],
                                     "observations": profile.get("observations")})
    if not scored:
        return original, evidence
    index = {action: position for position, action in enumerate(original)}
    ranked = sorted(original, key=lambda action: (-scored.get(action, -10_000), index[action]))
    evidence["applied"] = ranked != original
    evidence["reason"] = "promoted_observed_correlation"
    return ranked, evidence
