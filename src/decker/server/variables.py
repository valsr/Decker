"""Server-side registry of plugin-declared template variables and their cached values."""

import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from decker.common.variables import (
    CORE_VARIABLE_NAMES,
    is_valid_name,
    match_pattern,
    pattern_shape,
)
from decker.plugin.manifest import VariableSpec


class VariableConflict(Exception):
    """A declaration collides with a core variable or another plugin's variable."""


class _View(Mapping[str, str]):
    """Read-only mapping: ``in``/``[]`` show set values; ``get`` also answers ``""`` for declared-unset names."""

    def __init__(self, store: "VariableStore") -> None:
        self._store = store

    def __getitem__(self, key: str) -> str:
        return self._store.snapshot()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._store.snapshot())

    def __len__(self) -> int:
        return len(self._store.snapshot())

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value, ``""`` for a declared-but-unset name, else default."""
        return self._store.lookup(key, default)


class VariableStore:
    """Owns variable declarations, runtime registrations of concrete names and the value cache."""

    def __init__(self, on_change: Callable[[frozenset[str]], None] | None = None) -> None:
        self._on_change = on_change
        self._lock = threading.Lock()
        self._exact: dict[str, tuple[str, str]] = {}
        self._patterns: dict[str, tuple[str, str]] = {}
        self._concrete: dict[str, str] = {}
        self._values: dict[str, str] = {}

    def declare(self, plugin_id: str, specs: Sequence[VariableSpec]) -> None:
        """Replace the plugin's declarations; raises VariableConflict and changes nothing on a collision."""
        with self._lock:
            exact = {s.name: (plugin_id, s.description) for s in specs if s.name is not None}
            patterns = {s.pattern: (plugin_id, s.description) for s in specs if s.pattern is not None}
            self._check_conflicts(plugin_id, specs)
            changed = self._remove(plugin_id)
            self._exact.update(exact)
            self._patterns.update(patterns)
        self._notify(changed)

    def undeclare(self, plugin_id: str) -> None:
        """Remove everything the plugin declared, registered or set."""
        with self._lock:
            changed = self._remove(plugin_id)
        self._notify(changed)

    def owner_of(self, name: str) -> str | None:
        """Return the plugin declaring name, exactly or through a pattern."""
        with self._lock:
            return self._owner(name)

    def register(self, plugin_id: str, name: str) -> bool:
        """Register a concrete name inside one of the plugin's own patterns."""
        with self._lock:
            if self._exact.get(name, ("",))[0] == plugin_id or self._concrete.get(name) == plugin_id:
                return True
            if not is_valid_name(name) or name in self._exact or name in self._concrete or name in CORE_VARIABLE_NAMES:
                return False
            if self._pattern_owners(name) == {plugin_id}:
                self._concrete[name] = plugin_id
                return True
            return False

    def unregister(self, plugin_id: str, name: str) -> None:
        """Drop a concrete registration and its value."""
        with self._lock:
            if self._concrete.get(name) != plugin_id:
                return
            del self._concrete[name]
            changed = {name} if self._values.pop(name, None) is not None else set()
        self._notify(changed)

    def set_value(self, plugin_id: str, name: str, value: str | None) -> bool:
        """Cache a value for a name the plugin owns; None clears it."""
        with self._lock:
            if not self._owns_registered(plugin_id, name):
                return False
            old = self._values.get(name)
            if value is None:
                self._values.pop(name, None)
            else:
                self._values[name] = value
            changed = old != value
        if changed:
            self._notify({name})
        return True

    def drop_values(self, plugin_id: str) -> None:
        """Clear the plugin's values and concrete registrations, keeping its declarations."""
        with self._lock:
            names = [n for n in self._values if self._owns_registered(plugin_id, n)]
            changed = {n for n in names if self._values.pop(n, None) is not None}
            for name in [n for n, owner in self._concrete.items() if owner == plugin_id]:
                del self._concrete[name]
        self._notify(changed)

    def registered_names(self, plugin_id: str) -> list[str]:
        """Return the plugin's exact and registered concrete names, sorted."""
        with self._lock:
            return sorted(self._names_of(plugin_id))

    def snapshot(self) -> dict[str, str]:
        """Return a copy of the set values."""
        with self._lock:
            return dict(self._values)

    def view(self) -> Mapping[str, str]:
        """Return a live mapping usable as the variables of ``expand_template``."""
        return _View(self)

    def lookup(self, name: str, default: Any) -> Any:
        """Return the value of name, ``""`` when declared but unset, else default."""
        with self._lock:
            if name in self._values:
                return self._values[name]
            if name in self._exact or name in self._concrete or self._pattern_owner(name) is not None:
                return ""
            return default

    def listing(self) -> list[dict[str, Any]]:
        """Describe every exact and registered concrete name."""
        with self._lock:
            rows = [self._row(name, owner, "", desc) for name, (owner, desc) in self._exact.items()]
            for name, owner in self._concrete.items():
                pattern, desc = self._pattern_of(owner, name)
                rows.append(self._row(name, owner, pattern, desc))
        return sorted(rows, key=lambda row: row["name"])

    def _row(self, name: str, owner: str, pattern: str, description: str) -> dict[str, Any]:
        return {
            "name": name,
            "pattern": pattern,
            "description": description,
            "owner": owner,
            "value": self._values.get(name),
        }

    def _check_conflicts(self, plugin_id: str, specs: Sequence[VariableSpec]) -> None:
        shapes: set[str] = set()
        names: set[str] = set()
        for spec in specs:
            if spec.name is not None:
                self._check_name(plugin_id, spec.name, names)
            elif spec.pattern is not None:
                self._check_pattern(plugin_id, spec.pattern, shapes)

    def _check_name(self, plugin_id: str, name: str, seen: set[str]) -> None:
        owner = self._owner(name)
        if name in CORE_VARIABLE_NAMES or name in seen or (owner is not None and owner != plugin_id):
            raise VariableConflict(f"variable {name!r} is already taken")
        seen.add(name)

    def _check_pattern(self, plugin_id: str, pattern: str, seen: set[str]) -> None:
        shape = pattern_shape(pattern)
        if any(match_pattern(pattern, n) is not None for n in CORE_VARIABLE_NAMES) or any(
            owner != plugin_id and match_pattern(pattern, n) is not None for n, (owner, _) in self._exact.items()
        ):
            raise VariableConflict(f"variable pattern {pattern!r} shadows an existing variable")
        if shape in seen or any(
            owner != plugin_id and pattern_shape(other) == shape for other, (owner, _) in self._patterns.items()
        ):
            raise VariableConflict(f"variable pattern {pattern!r} is already taken")
        seen.add(shape)

    def _owner(self, name: str) -> str | None:
        if name in self._exact:
            return self._exact[name][0]
        return self._pattern_owner(name)

    def _pattern_owner(self, name: str) -> str | None:
        for pattern, (owner, _) in self._patterns.items():
            if match_pattern(pattern, name) is not None:
                return owner
        return None

    def _pattern_owners(self, name: str) -> set[str]:
        return {owner for pattern, (owner, _) in self._patterns.items() if match_pattern(pattern, name) is not None}

    def _pattern_of(self, plugin_id: str, name: str) -> tuple[str, str]:
        for pattern, (owner, desc) in self._patterns.items():
            if owner == plugin_id and match_pattern(pattern, name) is not None:
                return pattern, desc
        return "", ""

    def _owns_registered(self, plugin_id: str, name: str) -> bool:
        exact = self._exact.get(name)
        return (exact is not None and exact[0] == plugin_id) or self._concrete.get(name) == plugin_id

    def _names_of(self, plugin_id: str) -> list[str]:
        names = [n for n, (owner, _) in self._exact.items() if owner == plugin_id]
        return names + [n for n, owner in self._concrete.items() if owner == plugin_id]

    def _remove(self, plugin_id: str) -> set[str]:
        changed = {n for n in self._names_of(plugin_id) if self._values.pop(n, None) is not None}
        self._exact = {n: v for n, v in self._exact.items() if v[0] != plugin_id}
        self._patterns = {p: v for p, v in self._patterns.items() if v[0] != plugin_id}
        self._concrete = {n: o for n, o in self._concrete.items() if o != plugin_id}
        return changed

    def _notify(self, changed: set[str]) -> None:
        if changed and self._on_change is not None:
            self._on_change(frozenset(changed))
