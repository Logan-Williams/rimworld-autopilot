# Live Laya smoke test ledger

## Scope

Run commit `187bf120df0820d6173cb88eee10c88fe63cfe75` against the user-designated
test save `Поселение 1` through the existing local RIMAPI endpoint.  Its old
director state and logs are not inputs to the new run.

## Safety boundary

- Stop the existing director before starting the candidate: only one director
  may send commands to the game endpoint.
- Save the currently open colony before leaving it.
- The user designated `Поселение 1` as the test world; use new candidate-only
  state/log paths and do not reuse its old director state/logs.
- Do not reuse any old `colony-state.json`, preferences, decision history or
  pending construction plan.
- The smoke test may issue ordinary game commands only after candidate startup,
  RIMAPI reachability and log identity have been verified.

## Acceptance checks

1. The candidate process imports and starts from this exact commit with the
   installed local Laya runtime.
2. Candidate logs/state are created outside the current live installation and
   identify the candidate process.
3. RIMAPI ticks advance on a newly created map and the candidate has no startup
   traceback, action-description lookup failure, missing-anchor failure or
   memory error during the observed window.
4. The first accepted actions and later observations are recorded.  This only
   proves that commands were accepted/observed; it does not prove causal
   completion, autonomous victory or model training.
5. On any exception, pause the test and retain the isolated logs and receipt;
   do not fall back to the old director.

## Current blockers and evidence

- The current open game is attached to a divergent old installation, not this
  commit.  Its log has missing-anchor and large-response memory failures.
- This branch has no user runtime config or virtual environment by design;
  the test must point explicitly at the existing verified local Python/Laya
  environment while keeping the candidate state and logs separate.

## Status

`PAUSED FOR MCP CONTRACT` — the user requested a single MCP control boundary
and a chat-to-directive interface before candidate game commands.  The local
chat-to-typed-directive slice is implemented and offline-verified; it sends no
game command.  Candidate runtime preflight is complete; no candidate game
command has been sent.

## M3 chat application receipt

- The isolated source suite passed: `1446` tests, `2` skipped.
- The packaged control-center executable was smoke-tested before installation.
- The installed runtime at `D:\steam\RimWorld Autopilot` was updated from the
  generated payload after saving the prior runtime files in
  `D:\steam\RimWorld Autopilot\backups\chat-ui-20261012`.
- The update deliberately excluded `rimworld-autopilot.json`,
  `autopilot-preferences.json`, logs, the virtual environment, the active
  RIMAPI mod and all RimWorld saves.  Post-copy verification matched all `52`
  runtime payload files by SHA-256.
- The new GUI and chat compiler send no RIMAPI request.  MCP integration still
  owns future live observation/status handoff.

## Next action

Verify the team-owned MCP contract and its safe integration with chat
directives, then load `Поселение 1` and run the candidate with isolated logs.
