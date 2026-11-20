from assertpy import assert_that

from decker.common.template import expand_template
from decker.plugin.manifest import VariableSpec
from decker.server.variables import VariableConflict, VariableStore


def _name(name: str) -> VariableSpec:
    return VariableSpec(name=name, pattern=None, description=f"desc {name}")


def _pattern(pattern: str) -> VariableSpec:
    return VariableSpec(name=None, pattern=pattern)


def _declared(store: VariableStore, plugin_id: str, *specs: VariableSpec) -> None:
    store.declare(plugin_id, list(specs))


def test_spec_requires_exactly_one_of_name_and_pattern() -> None:
    for kwargs in ({"name": None, "pattern": None}, {"name": "a", "pattern": "b_{x}"}):
        try:
            VariableSpec(**kwargs)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_declare_exact_and_owner() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("weather"), _pattern("sensor_{id}"))
    assert_that(store.owner_of("weather")).is_equal_to("p1")
    assert_that(store.owner_of("sensor_kitchen")).is_equal_to("p1")
    assert_that(store.owner_of("other")).is_none()
    assert_that(store.registered_names("p1")).is_equal_to(["weather"])


def test_declare_rejects_core_name() -> None:
    store = VariableStore()
    try:
        _declared(store, "p1", _name("page_name"))
    except VariableConflict:
        pass
    else:
        raise AssertionError("expected conflict")
    assert_that(store.owner_of("page_name")).is_none()


def test_declare_rejects_name_owned_by_another_plugin() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("weather"))
    try:
        _declared(store, "p2", _name("weather"))
    except VariableConflict:
        pass
    else:
        raise AssertionError("expected conflict")
    assert_that(store.owner_of("weather")).is_equal_to("p1")


def test_declare_rejects_name_matching_other_pattern() -> None:
    store = VariableStore()
    _declared(store, "p1", _pattern("sensor_{id}"))
    try:
        _declared(store, "p2", _name("sensor_a"))
    except VariableConflict:
        pass
    else:
        raise AssertionError("expected conflict")


def test_declare_rejects_identical_pattern_shape() -> None:
    store = VariableStore()
    _declared(store, "p1", _pattern("sensor_{id}"))
    try:
        _declared(store, "p2", _pattern("sensor_{other}"))
    except VariableConflict:
        pass
    else:
        raise AssertionError("expected conflict")


def test_declare_is_atomic() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("taken"))
    try:
        _declared(store, "p2", _name("fresh"), _name("taken"))
    except VariableConflict:
        pass
    else:
        raise AssertionError("expected conflict")
    assert_that(store.owner_of("fresh")).is_none()
    assert_that(store.registered_names("p2")).is_empty()


def test_redeclare_replaces_previous_declarations() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("old"))
    _declared(store, "p1", _name("new"))
    assert_that(store.owner_of("old")).is_none()
    assert_that(store.owner_of("new")).is_equal_to("p1")


def test_register_concrete_in_own_pattern_only() -> None:
    store = VariableStore()
    _declared(store, "p1", _pattern("sensor_{id}"))
    _declared(store, "p2", _pattern("light_{id}"))
    assert_that(store.register("p1", "sensor_a")).is_true()
    assert_that(store.register("p1", "light_a")).is_false()
    assert_that(store.register("p1", "other")).is_false()
    assert_that(store.register("p1", "Sensor_A")).is_false()
    assert_that(store.register("p3", "sensor_b")).is_false()
    assert_that(store.registered_names("p1")).is_equal_to(["sensor_a"])


def test_set_value_only_by_owner() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("weather"), _pattern("sensor_{id}"))
    assert_that(store.set_value("p1", "weather", "sunny")).is_true()
    assert_that(store.set_value("p2", "weather", "rain")).is_false()
    assert_that(store.set_value("p1", "sensor_a", "1")).is_false()
    store.register("p1", "sensor_a")
    assert_that(store.set_value("p1", "sensor_a", "1")).is_true()
    assert_that(store.snapshot()).is_equal_to({"weather": "sunny", "sensor_a": "1"})


def test_set_value_none_clears() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("weather"))
    store.set_value("p1", "weather", "sunny")
    assert_that(store.set_value("p1", "weather", None)).is_true()
    assert_that(store.snapshot()).is_empty()


def test_on_change_only_when_value_changes() -> None:
    changes: list[frozenset[str]] = []
    store = VariableStore(on_change=changes.append)
    _declared(store, "p1", _name("weather"))
    store.set_value("p1", "weather", "sunny")
    store.set_value("p1", "weather", "sunny")
    store.set_value("p1", "weather", "rain")
    store.set_value("p1", "weather", None)
    store.set_value("p1", "weather", None)
    assert_that(changes).is_equal_to([frozenset({"weather"})] * 3)


def test_drop_values_keeps_exact_declarations_drops_concrete() -> None:
    changes: list[frozenset[str]] = []
    store = VariableStore(on_change=changes.append)
    _declared(store, "p1", _name("weather"), _pattern("sensor_{id}"))
    store.register("p1", "sensor_a")
    store.set_value("p1", "weather", "sunny")
    store.set_value("p1", "sensor_a", "1")
    changes.clear()
    store.drop_values("p1")
    assert_that(store.snapshot()).is_empty()
    assert_that(store.registered_names("p1")).is_equal_to(["weather"])
    assert_that(store.owner_of("weather")).is_equal_to("p1")
    assert_that(changes).is_equal_to([frozenset({"weather", "sensor_a"})])


def test_undeclare_frees_name_for_another_plugin() -> None:
    changes: list[frozenset[str]] = []
    store = VariableStore(on_change=changes.append)
    _declared(store, "p1", _name("weather"), _name("unset"))
    store.set_value("p1", "weather", "sunny")
    changes.clear()
    store.undeclare("p1")
    assert_that(changes).is_equal_to([frozenset({"weather"})])
    assert_that(store.owner_of("weather")).is_none()
    _declared(store, "p2", _name("weather"))
    assert_that(store.owner_of("weather")).is_equal_to("p2")


def test_unregister_drops_registration_and_value() -> None:
    store = VariableStore()
    _declared(store, "p1", _pattern("sensor_{id}"))
    store.register("p1", "sensor_a")
    store.set_value("p1", "sensor_a", "1")
    store.unregister("p1", "sensor_a")
    assert_that(store.registered_names("p1")).is_empty()
    assert_that(store.snapshot()).is_empty()


def test_view_returns_empty_for_declared_unset_and_default_otherwise() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("weather"), _pattern("sensor_{id}"))
    view = store.view()
    assert_that(view.get("weather", "dflt")).is_equal_to("")
    assert_that(view.get("sensor_zzz", "dflt")).is_equal_to("")
    assert_that(view.get("unknown", "dflt")).is_equal_to("dflt")
    store.set_value("p1", "weather", "sunny")
    assert_that(view.get("weather", "dflt")).is_equal_to("sunny")
    assert_that(view["weather"]).is_equal_to("sunny")
    assert_that(list(view)).is_equal_to(["weather"])
    assert_that(len(view)).is_equal_to(1)


def test_listing_describes_exact_and_registered_names() -> None:
    store = VariableStore()
    store.declare("p1", [_name("weather"), VariableSpec(name=None, pattern="sensor_{id}", description="sensors")])
    store.register("p1", "sensor_a")
    store.set_value("p1", "sensor_a", "1")
    assert_that(store.listing()).is_equal_to(
        [
            {"name": "sensor_a", "pattern": "sensor_{id}", "description": "sensors", "owner": "p1", "value": "1"},
            {"name": "weather", "pattern": "", "description": "desc weather", "owner": "p1", "value": None},
        ]
    )


def test_snapshot_only_set_values() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("a"), _name("b"))
    store.set_value("p1", "a", "1")
    assert_that(store.snapshot()).is_equal_to({"a": "1"})


def test_value_text_expansion_is_not_recursive() -> None:
    store = VariableStore()
    _declared(store, "p1", _name("weather"))
    store.set_value("p1", "weather", "{page_name}")
    assert_that(expand_template("now {weather}", store.view())).is_equal_to("now {page_name}")
