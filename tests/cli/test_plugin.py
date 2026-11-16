import pytest
from assertpy import assert_that

from decker.cli import plugin as plugin_cli
from decker.cli.connection import CliConnection


class FakeConn(CliConnection):
    def __init__(self, reply=None, error=None):  # pylint: disable=super-init-not-called
        self.calls = []
        self._reply = reply
        self._error = error

    def request(self, name, *args):
        self.calls.append((name, args))
        if self._error:
            raise self._error
        return self._reply


def test_install_sends_bytes_over_rpc(tmp_path):
    package = tmp_path / "a-1.0.0.deckerplugin"
    package.write_bytes(b"PK-data")
    conn = FakeConn(reply=12345)
    assert_that(plugin_cli.install(conn, package)).is_equal_to("12345")
    assert_that(conn.calls).is_equal_to([("plugin_install", ("a-1.0.0.deckerplugin", b"PK-data"))])


def test_install_permission_error_has_clear_message(tmp_path):
    package = tmp_path / "a.deckerplugin"
    package.write_bytes(b"x")
    with pytest.raises(plugin_cli.PluginCliError, match="only allowed from the server's own machine"):
        plugin_cli.install(FakeConn(error=PermissionError("denied")), package)


def test_install_missing_file(tmp_path):
    with pytest.raises(plugin_cli.PluginCliError, match="cannot read"):
        plugin_cli.install(FakeConn(), tmp_path / "missing.deckerplugin")


def test_remove_and_list_use_rpc():
    conn = FakeConn(reply=[{"id": "com.x.y"}])
    assert_that(plugin_cli.list_plugins(conn)).is_equal_to([{"id": "com.x.y"}])
    plugin_cli.remove(conn, "com.x.y")
    assert_that(conn.calls).is_equal_to([("plugins_list", ()), ("plugin_uninstall", ("com.x.y",))])


def test_list_non_list_reply_is_empty():
    assert_that(plugin_cli.list_plugins(FakeConn(reply=None))).is_empty()


def test_remove_permission_error():
    with pytest.raises(plugin_cli.PluginCliError, match="only allowed"):
        plugin_cli.remove(FakeConn(error=PermissionError("denied")), "com.x.y")
