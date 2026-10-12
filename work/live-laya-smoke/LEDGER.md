# Live Laya smoke test ledger

## Scope

Run the exact clean commit recorded by `Start-Candidate.ps1` against the
user-designated test save `Поселение 1`.  The operator reads the game only
through MCP; Laya's existing executor is the sole component permitted to send
its ordinary game commands.  The old director state and logs are not inputs to
the new run.

## Safety boundary

- Stop the existing director before starting the candidate: only one director
  may send commands to the game endpoint.
- Save the currently open colony before leaving it.
- The user designated `Поселение 1` as the test world; use new candidate-only
  state/log paths and do not reuse its old director state/logs.
- Publish only the candidate's lifecycle status to
  `D:\steam\RimWorld Autopilot\runtime-status.json`, the status location
  recognized by MCP.  Its PID, state and decision log remain isolated.  While
  it reports `running`, MCP manual writes must fail closed.
- Do not reuse any old `colony-state.json`, preferences, decision history or
  pending construction plan.
- The smoke test may issue ordinary game commands only after candidate startup,
  RIMAPI reachability and log identity have been verified.

## Acceptance checks

1. The candidate process imports and starts from this exact commit with the
   installed local Laya runtime.
2. Candidate logs/state are created outside the current live installation and
   identify the candidate process.
3. MCP shows ticks advancing on the loaded map and the candidate has no startup
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
- MCP v0.1.1 read-only startup diagnostics proved the first technical launch
  reached Python argument parsing but not the model/API: `candidate.stderr`
  reported `unrecognized arguments: Autopilot\\runtime-status.json`.  The
  Windows launcher had split the status path at its space.  There were no
  candidate PID, status, decisions, Laya decisions or Ornith calls.

## Status

`PREPARING EXCLUSIVE LIVE TEST` — the user requested an MCP-coordinated test
of Laya and Ornith on `Поселение 1`.  Stop the old director first, load the
fresh test-map session, take a read-only receipt, then start only this
candidate.  The MCP owner observed `Playing`, tick `330`, three pawns and
zero MCP POSTs after the user loaded the save.  No candidate game command has
been sent yet.

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

Verify the launcher quotes every path argument, commit the fix, then verify
the standard MCP-visible runtime status is stopped before running the sole
candidate.  Confirm from MCP that it publishes `running`, observe at least
three fresh snapshots, and stop on the first safety failure.
