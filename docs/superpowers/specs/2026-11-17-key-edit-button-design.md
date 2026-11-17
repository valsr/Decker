# Key edit button — design

Status: awaiting approval. Size: small change (client only).

## Intent

In the dashboard a click on a key both **selects** it (shows its configuration) and **sends a press to the server**, so
configuring a Counter increments it. Selecting and acting must be separate: a small pencil appears in the key's top
right corner on hover and selects the key for editing; clicking the key itself only performs the action.

## Goals

- Hovering a key shows a pencil button in its top-right corner; leaving the key hides it. Tooltip "Edit this key".
- Clicking the **pencil**: selects the key and shows its configuration. It does **not** press the key.
- Clicking the **key** (anywhere else): performs the action (press, and long press as today). It does **not** change the
  selection.
- Drag-and-drop of an action onto a key is unchanged.
- Keyboard: **F2** (or the Menu key) on a focused key edits it, and the pencil is shown while a key has keyboard focus. (Added after review: without it a keyboard user could no longer open a key's configuration.)
- The configuration panel's empty-state text explains the new gesture: "Hover a key and click ✎ (or focus it and press F2) to configure it".
- The pencil has its own theme rule (a small disc, no padding) so its glyph is not clipped by the generic tool-button padding.

## Non-goals

- A visual "selected" highlight on the key (none exists today; can follow).
- Touch access to the pencil (there is no hover on touch screens).

## Design (decker, `client/widgets/button_grid.py`, `client/views/dashboard.py`)

- `KeyButtonWidget` gets a child `QToolButton` (pencil drawn from the shipped `src/decker/assets/edit.svg`, filled with the palette's text colour and redrawn on a palette change, with a "✎" glyph fallback if the file is unusable), 30 px, 4 px from
  the top-right corner, hidden until the pointer enters the key. `edit_clicked = pyqtSignal(int)` carries the key index.
  The pencil stays visible while the pointer is over the pencil itself (it is a child of the key).
- `ButtonGridWidget`: new signals `key_pressed(int)` (from the key's `clicked`) and `key_edit_requested(int)` (from the pencil);
  `key_selected` is removed.
- `DashboardView`: `_on_key_pressed(index)` only calls `key_simulate_press`; `_on_key_edit_requested(index)` is today's
  selection logic without the press.
- The pencil is shown on every key, including empty ones (selecting an empty key shows the same state as today).

## Calls made without you

- Pencil on all keys, not only assigned ones; "✎" glyph only as a fallback when `edit.svg` is missing or unreadable.
