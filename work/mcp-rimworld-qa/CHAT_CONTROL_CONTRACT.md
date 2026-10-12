# Contract: player chat and RimWorld MCP

## Purpose

The Laya desktop application needs a Russian-language player chat.  A message
such as «колонистам холодно» is not a game command and must never be presented
as one.  It becomes a small, typed player directive which the director can
consider only against a fresh colony observation and its existing safe action
frontier.

The MCP server is the one owner of the game boundary.  The GUI must not issue
arbitrary HTTP requests or let a chat model choose an undocumented RIMAPI
endpoint.

## Typed directives for the first slice

| Player wording | Canonical directive | Director effect | Completion evidence |
| --- | --- | --- | --- |
| «Холодно», «согрей колонистов» | `thermal_safety` | Prefer existing native shelter/heating candidates after emergency gates. | Fresh room/pawn temperature observation improves or shows no risk. |
| «Сначала еда», «не ешь сырое без нужды» | `prepared_food` | Prefer cooking/meal candidates only in a non-emergency state. | Fresh food budget and prepared-meal observation. |
| «Сначала дом» | `shelter_first` | Defer discretionary development while real shelter is missing. | Observed roofed, enclosed sleeping capacity. |
| «Торгуй мирно» | `peaceful_trade` | Persist the existing safe preference; no attack candidates are invented. | Preference saved and next cycle records the filtered frontier. |
| «Остановись / не делай этого» | `hold_and_explain` | Stop only the candidate's discretionary decision path; never hides medical, food, fire or rescue gates. | MCP returns status and the next available stop boundary. |

Each directive contains: `id`, `source_text` (bounded and local), `created_at`,
`map_fingerprint`, `state` (`proposed`, `active`, `blocked`, `observed`,
`expired`), `evidence`, `allowed_actions`, `forbidden_actions`, and an
explanation for the player.  A directive from an earlier map or a rewound tick
is invalidated rather than replayed.

## Clothes are an explicit blocker, not a promise

`thermal_safety` can safely favour an already available heating/shelter action.
It cannot claim «Laya dressed the colonists» until RIMAPI supplies, per pawn and
per loose apparel item:

1. worn apparel identity, insulation, durability and current temperature risk;
2. loose item identity, insulation, reachability, reservation and forbidden
   state;
3. one exact validated `wear_apparel(pawn_id, apparel_id)` action;
4. a follow-up observation proving the item is worn.

Before all four facts exist, the MCP/chat response is `blocked` with the
missing facts.  It sends no name-based apparel command.

## MCP boundary

The backend owns one local stdio MCP server with typed tools.  The minimum
contract is:

- `observe_colony` — GET-only, returns a bounded anonymous status summary and
  map fingerprint.
- `submit_player_directive` — validates a known canonical directive, map
  fingerprint and bounded text; records it locally but does not send a RimWorld
  command itself.
- `get_directive_status` — returns state, evidence and blockers.
- `start_candidate` / `stop_candidate` — explicit lifecycle operations with
  isolated state/log paths, never a raw shell input tool.

No tool accepts a free endpoint, a raw HTTP method, a shell command, a pawn name
as authority, or an arbitrary JSON body.  Mutating candidate actions remain in
the director's current validation chain, not in the chat parser.

## Learning boundary

Chat feedback can store a labelled, anonymous outcome: directive, map
fingerprint, candidate action, accepted/rejected state and later observed
delta.  It may change the ranking of existing low-risk candidates only after
the current multi-observation promotion rule.  It does **not** train Laya's
weights in the active game and does not turn an unobserved command into a
positive example.

An actual model-training experiment remains offline: frozen baseline, bounded
sanitized episodes, identical simulator scenarios, safety/regression metrics
and a human-reviewed candidate promotion.  A chat message is a priority and
feedback signal, not a training label by itself.

## GUI integration

Add a `Chat` page beside the existing priorities and personal note UI.  The
page shows the submitted wording, resolved directive, current map fingerprint,
allowed/blocked status, observation evidence and a clear `not executed` state.
It calls only the MCP tools above.  The existing preferences file remains the
durable source of normal priority sliders and the personal note.

### Implemented local chat slice (M3)

The desktop app now has a `Chat with Laya` page and an offline,
deterministic directive compiler.  It recognizes the five typed goals listed
above, saves a bounded local transcript and sends only canonical directive IDs
plus the matching map fingerprint/tick to Laya's decision context.  The
transcript and the original player wording never become model input.

This M3 slice does not call RimWorld or an LLM.  It visibly reports `not
executed`, and leaves candidate lifecycle and any future read/status calls to
the MCP server.  A free-form conversational model can be added later only
behind the same typed-directive validator; it must not become a direct game
control path.

## Acceptance tests

1. A cold message resolves to `thermal_safety`; the resulting action set is a
   subset of the existing director frontier.
2. A clothing request returns `blocked` when apparel facts are absent and sends
   no RIMAPI mutation.
3. A stale/re-wound map fingerprint invalidates an active directive.
4. Free endpoint, raw shell and unknown-directive inputs are rejected.
5. The chat renders a distinction between `accepted command`, `observed change`,
   `blocked`, and `not executed`.
6. The same directive cannot bypass food, medical, fire, combat or rescue
   gates.
