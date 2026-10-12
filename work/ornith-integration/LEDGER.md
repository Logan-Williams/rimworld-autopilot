# Ornith advice integration — task ledger

## User-visible goal

Connect local Ornith to Laya so it can give a bounded, evidence-backed recommendation for the already safe list of actions. Laya remains the only decider and executor. Record actual command results as experience; do not claim model-weight training.

## Controls

- No screenshots, UI automation, direct RimAPI operation, or live-game launch in this slice.
- The adviser can see only compact observed facts and the current safe candidate frontier.
- Ornith may never invent a new action, bypass feasibility/backoff rules, or send a game command.
- Laya must explicitly accept an advice result; normal execution and result checks stay unchanged.
- The existing repeat-error evidence for `equip_colonists` is tracked as a separate defect slice.

## Slices and acceptance

1. Adopt the established local `ornith_advice.v3` module without its personal configuration or secrets. Import-only validation must pass.
2. Call adviser preparation after the director has applied safety, preference, behavioural and learning filters. A regression test must prove the adviser receives the current frontier and cannot expand it.
3. Persist adviser audit and observed execution result, while the existing learning layer continues to stage only accepted commands. Tests must prove Laya can reject advice and stay independent.
4. Diagnose and correct the repeated `equip_colonists` failure backoff with a failing regression before implementation.
5. Run focused and full offline tests, then a separate source review. A future live run needs a fresh MCP-only preflight and user-visible runtime receipt.

## Current evidence and next action

- Live smoke on `Поселение 1` was stopped after five `equip_target_unreachable_or_reserved` failures. The director process is stopped; do not infer that the paused/unpaused game state changed.
- Clean candidate source had no Ornith/adviser import or call. The locally proven adviser module exists outside this repository and does not execute game commands.
- The source now contains `colony_advisor.py`; against the established local reference its only intentional functional difference is default `enabled: false`. An explicit profile enables it. The candidate's untracked local profile is deliberately excluded from Git and must never be committed.
- `colony_director.py` sends Ornith only the post-filtered candidate frontier, rejects any expanded/empty returned frontier, records adviser audit plus command result, and continues with Laya when advice fails.
- The live failure root cause was confirmed: `equip_colonists` was explicitly excluded from general action backoff whenever an error reason was present. The exception is removed and covered by a regression test.
- GUI source has an `ornith_enabled` opt-in. On its next Laya start it creates a non-secret local profile only if needed and passes its path to the director. The PowerShell launcher also has `-WithOrnith`.
- Offline evidence: 19 established adviser regressions, then 26 focused integration/learning/install regressions, then the full suite (`1451` passed, `2` skipped). These tests use mocked transports or replay fixtures; they are not a live-game/model acceptance.
- Source review is pending on this exact worktree. Rebuilding/deploying the user-facing GUI and a fresh MCP-only live preflight are separate next steps; no director restart, model call, or game action occurred in this implementation slice.
