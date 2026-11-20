# Switch card — design

Status: draft for approval. Date: 2026-11-20.

## Intent

A **Switch** card gives one key several behaviours: it shows a card, and its press, double press and long press each
either run an action or swap the card the key shows. It is the first of the "MultiAction" plugins in the todo list
(Stack comes later and should reuse the slot machinery built here).

## Behaviour

Four **slots**: Display, Press, Double Press, Long Press.

- **Display** holds a card (never an action). It is what the key shows first.
- **Press / Double Press / Long Press** each hold a card, an action, or nothing.
  - An **action** runs headlessly (`ActionRunner`); the key face does not change.
  - A **card** becomes the card shown on the key. The Switch keeps all input handling; the shown card draws its
    face (live state, animation) but receives no key events and does not recognise gestures.
- **Fallback face:** with no Display card, a Press slot holding a card is shown. Otherwise (Press empty or an action)
  the Switch draws its own face from its shared title, icon and background.
- **Shown-card state** is in memory only, keyed by the Switch's context id. It survives page and profile switches and
  is lost when the server restarts. Nothing is written to the stored page, key or profile (same rule as the
  screensaver).
- Only gestures with a filled slot are registered, so a Switch with just Press responds to a press without waiting for
  the double-press window.
- When a card is shown, that card's face replaces the Switch's entirely, including its own title and icon.
- Switching to the card already shown does nothing. A Switch cannot be placed inside a Switch slot (no nesting in v1).

## Goals

- Drop-to-fill slots in the settings UI; per-slot configuration of the selected slot.
- Server-native, no plugin process for the Switch itself; works with no client running.
- Slot machinery (a `slot` settings type, child live contexts) reusable by Stack.

## Non-goals

- Third-party plugins hosting child cards (the protocol surface stays unchanged; revisit later).
- Nested Switches, Stack, per-slot conditions, persisting the shown card across restarts.

## Constraints

- Server and client stay decoupled; the client never talks to hardware (CLAUDE.md).
- Waking the screensaver swallows key events, so no slot ever fires from a wake press.
- Cross-platform; no platform-specific code is needed.
- Plugin docs (`docs/plugins/`) and `CLAUDE.md` change with the manifest and settings-schema additions.

## Approaches considered

- **A. Server-native Switch in Core (chosen).** Child cards are hosted by the server on the Switch's key. State is
  in memory. Most server work, but the behaviour is tightly coupled to key and gesture handling and the state rules
  stay simple.
- **B. Out-of-process Switch plugin.** Needs new public protocol messages (`run_action`, `show_card`, child
  contexts), a stdin/stdout round trip per press, and plugin-held state that a plugin restart would reset. Can be
  built later on top of A's child-context machinery.
- **C. Client-side composition.** Rejected: the server must switch the face with no client running.

## Design

### Data model

The Switch card declares one setting, `slots`, of new type `slots`, with value:

```json
{
  "display":      {"kind": "card",   "plugin": "...", "card": "...",   "settings": {}, "appearance": {}},
  "press":        {"kind": "action", "action": "...", "settings": {}},
  "double_press": null,
  "long_press":   {"kind": "card",   "plugin": "...", "card": "...",   "settings": {}, "appearance": {}}
}
```

Child cards and actions are embedded in the Switch's settings, so they move, copy and delete with the Switch and need
no separate store rows. Copying a key (`key_copy`) therefore copies its slots. The Switch's own `appearance`
(title, icon, background) is the shared button configuration.

### Server

- `CardSpec` gains a `switch` flag set from the manifest (`"behavior": "switch"`), next to `bound` and `static`.
  Core's manifest gains the Switch card (`gestures` is computed at runtime from filled slots).
- A new `SwitchController` (own module under `src/decker/server/`) owns the shown-card state and the slot logic:
  resolve the shown slot (shown state, else Display, else Press-if-card, else none), and handle an emitted gesture.
- `PluginManager` hosts the shown child as a second `_Live` with a synthetic context id
  (`<switch context id>:<slot>`) on the same device and key, with settings and appearance taken from the slot value
  rather than `settings_store`. `_Live` gets an optional `parent` context id. Only the shown child is live; swapping
  deactivates the old child and activates the new one, so plugin processes are acquired only for what is visible.
- Plugin messages for a child (`set_image`, `set_title`, `set_settings`, `switch_page`, …) route by its context id
  as today. `set_settings` from a child writes back into the parent's slot value.
- `dispatch_key_down/up` for a Switch feed the Switch's own `GestureRecognizer`; the child receives nothing.
  `_gesture_emitter` for a Switch calls `SwitchController` instead of sending the gesture to a plugin.
- Actions from a slot go through `run_action`; failures already surface as `action_failed`.
- Settings validation: `apply_schema` understands `slots` and drops slots whose card or action is uninstalled from
  behaviour (kept in the stored value so reinstalling restores them); a missing Display card falls back as above.
- `key_preview` composes the Switch's resolved face, so the editor preview matches the key.

### Client

- New settings field type `slots` in `schema_form.py`: a `SlotsEdit` widget with four faux buttons (icon of the
  held card or action, label under it, an empty state, a clear badge). Each accepts the picker drag payload
  (`application/x-decker-card`, including `preset_action`) via `dragEnterEvent`/`dropEvent`; Display rejects actions.
- Selecting a faux button shows that slot's configuration under the shared Switch button configuration: the held
  card's settings form and appearance, or the action's settings form (the existing `ActionParamsEdit`).
- Slot edits go through the normal card save (`CardConfigPanel`), not a new RPC.

### Docs and tests

- `docs/plugins/settings-schema.md` (the `slots` type), `package-and-manifest.md` (`behavior`), `CLAUDE.md`,
  `README.md`.
- Integration-style tests against real components: `SwitchController` slot resolution and fallback rules, gesture
  registration from filled slots, child activation/swap, shown-state surviving a page switch, state reset on a new
  `PluginManager`, slot value round trip and `key_copy`, `SlotsEdit` drop handling.

## Left to the builder

- Exact module split and names, the `slots` value validation details, icon and label rendering of faux buttons,
  and how an uninstalled child card is shown on its faux button.
