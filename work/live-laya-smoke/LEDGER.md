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

## Live MCP receipt: clean candidate

- Fresh MCP preflight observed the same loaded map `0:16622162:27402`, three
  pawns, no hostiles, advancing tick `63389 -> 63395`, `paused=false`, zero
  MCP POSTs, and the explicit stopped preflight receipt before launch.
- The sole clean candidate is commit
  `6d4b3d50e1b6c337d64f748505d491e4becb8329`, launcher PID `29836`, real
  Python director PID `4444`.  Its status was MCP-observed as fresh `running`.
- Three MCP samples showed advancing ticks `70143 -> 71101 -> 72040` on the
  same map, no endpoint errors or traceback, and zero MCP POSTs.  Laya loaded
  CUDA in `42.22s`; the recorded prediction time was `29.34ms`.
- Observed accepted work: `unforbid_supplies` made existing meals reachable
  (`0 -> 54`); `build_starter_base` created 28 native projects (23 walls, one
  door, three beds and one torch lamp).  These facts do not claim that the
  food was produced or the base was complete.
- Follow-up MCP samples advanced `79300 -> 80513 -> 81737` with the director
  still running, no fatal/errors and no MCP POSTs.  Projects fell `28 -> 18 ->
  12`; walls and beds progressed from blueprints to frames and one bed frame
  reached `21.7%`.  Alerts were empty.  Meals varied `48 -> 40 -> 48`.
- Open facts, not accepted successes: direct priority changes for several
  work types were `applied=false` because the effect was not observed; the
  dry-stockpile footprint was not observed.  Ornith is not part of this clean
  candidate: an exact-source search found no advisor import/call or configured
  Ornith loopback path in `colony_director.py`.  A saved `colony_advisor.py`
  is not an integration.  No manual repair command was issued.

## Next action

Keep the sole Laya candidate under MCP read-only observation.  First add a
bounded candidate decision view and an explicit advisor-availability view;
they must report `integration_not_observed` rather than infer an Ornith call.
Design and separately test any real Ornith integration before enabling it in a
live colony.
