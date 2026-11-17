# Select-on-click keys, a play icon, and drag-and-drop move/copy — design

Status: approved in conversation. Size: small project (one repo: `decker`).

## Intent

Today clicking a key in the client presses it and a hover pencil edits it. Users expect a click to select, so the roles
swap: clicking a key selects it for editing, and a corner icon runs the action. With selection solved, keys can be
rearranged by dragging, and copied by dragging with Ctrl held.

## Goals

- **Click selects.** Clicking a key emits the edit request (what the pencil did): the key is outlined and the editor
  opens. F2 / the Menu key still edit.
- **Play icon.** The top-right hover control shows the `play-circle` icon (`src/decker/assets/play-circle.svg`) instead of the
  pencil, with the same visibility rules (hover or keyboard focus) and position. Pressing it behaves exactly as clicking the
  key did before: a click is a key press, holding it for 0.5 s is a long press. Tooltip: "Run this key".
- **Drag to move.** A key with an assigned action can be dragged. Dropping it on another key of the same page moves the
  action there: whatever was on the target is removed, the source becomes empty, and the action instance keeps its identity,
  settings, appearance and plugin state.
- **Ctrl-drag to copy.** Dropping with Ctrl held copies instead: the source stays, the target's previous action is removed, and
  the target gets a new instance (new context id) with the same settings and appearance. While Ctrl is held over a key during
  a drag, a green `plus-circle` badge shows at that key's bottom-left.
- **Afterwards** the destination key is selected for editing.
- **Server.** New RPCs `key_move(device_id, page_id, from_index, to_index) -> bool` and
  `key_copy(device_id, page_id, from_index, to_index) -> bool`, each atomic. They return false (changing nothing) for an
  unknown page, an empty source, `from == to`, or an index outside the device's keys.

## Non-goals

- Dragging between pages, onto page tabs, between devices or between profiles.
- Dragging empty keys, multi-select, undo.
- A confirmation before replacing an occupied target (replacement is the specified behaviour).
- A keyboard shortcut for pressing a key (Space/Enter select it; the play icon is the pointer route).
- Removing `edit.svg` (it stays in the assets, unused, for now).

## Anti-goals

- A move that loses the instance's plugin settings/state (which a client-side unassign + assign would).
- A half-applied move or copy if something fails midway.
- Accidental drags: a plain click must still just select.

## Approaches considered

1. **Two server RPCs (chosen).** The server owns the key rows, the live instances and the cached images, so it can swap
   them in one step and keep the context id on a move.
2. Client-side `key_unassign` + `key_assign` calls. Not atomic, a move would get a new context id (losing plugin state), and
   a copy would have to resend settings and appearance. Rejected.

## Design

### Server

- `KeyAssignmentStore.move(device_id, page_id, from_index, to_index) -> bool`: in one transaction delete the target row and
  re-key the source row (same context id, settings, appearance).
- `PluginManager`/`DeckerService`: `key_move` — deactivate the source and target instances, clear the cached key state of both
  slots, move the row, and if the page is the device's active page activate the instance at its new index (same context
  id; `store_settings` as `PageController._show` does) and redraw. `key_copy` — deactivate the target, clear its state, add
  a copy of the source row with a new context id (`KeyAssignmentStore.assign` + settings + appearance), activate it if the
  page is active. Both reuse the validation and locking style of `key_assign` / `key_unassign`.
- The server pushes `key_state_changed` for the changed slots as it already does when an instance draws.

### Client

- `KeyButtonWidget`: `clicked` emits `edit_clicked` (selection); the former pencil `QToolButton` becomes the play button
  (`play-circle.svg`, same recolouring as the pencil) and carries the press / long-press logic the key itself had, emitting
  `press_requested` / `long_pressed`; `ButtonGridWidget` forwards them as `key_pressed` / `key_long_pressed`.
- Drag source: `set_draggable(bool)` (set by the dashboard for keys with an action). Moving the pointer past the application
  drag distance with the left button down starts a `QDrag` with a `application/x-decker-key` payload `{"key_index": n}` and
  the key's pixmap. Drop target: the existing `dropEvent` also accepts the key payload, emits `key_moved(from, to, copy)`
  with `copy = Ctrl held`; `dragMoveEvent` toggles the green `plus-circle` badge (bottom-left, `plus-circle.svg` recoloured
  green) by Ctrl state; `dragLeaveEvent` and drop hide it.
- Dashboard: `key_moved` calls `key_move` / `key_copy` for the active device and page, then selects the target and requests a
  device refresh; a failed call changes nothing.
- Docs: `CLAUDE.md` and the plugin protocol/key RPC notes mention the new RPCs where RPCs are listed.

## Testing

TDD. Store: move re-keys the row keeping the context id, replaces an occupied target, refuses empty/same/out-of-range.
Service: move and copy on the active and an inactive page (live instance only on the active one), plugin deactivation and
activation calls, state clearing, copy gets a new context id with equal settings/appearance, invalid inputs return false.
Client (offscreen Qt): click selects and does not press; the play button presses and long-presses; F2 edits; drag starts only
past the drag distance and only for draggable keys; drop emits `key_moved` with the copy flag from Ctrl; the badge shows on
Ctrl drag-over and hides on leave/drop; dashboard wiring (RPC called, target selected, failure leaves the selection).

## Left to the builder

Exact badge size and colour (a clear green such as `#2ecc71`), the drag ghost's look, and the order of tasks.
