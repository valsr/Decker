import sys
from argparse import ArgumentParser
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.asset.store import IconPackStore
from decker.cli.app import create_parser, main

_SAMPLE_COMMANDS = {
    "stop": {"description": "Stop the application", "return_type": "bool", "params": ""},
    "status": {"description": "Get status", "return_type": "dict", "params": ""},
}


def _make_conn(commands=None, request_return=None):
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.commands.return_value = commands or _SAMPLE_COMMANDS
    conn.request.return_value = request_return
    return conn


class TestCreateParser:
    def test_returns_argument_parser(self):
        assert_that(create_parser()).is_instance_of(ArgumentParser)

    def test_has_host_argument(self):
        args = create_parser().parse_args([])
        assert_that(args.host).is_none()

    def test_has_port_argument(self):
        args = create_parser().parse_args([])
        assert_that(args.port).is_none()

    def test_has_verbose_argument(self):
        args = create_parser().parse_args([])
        assert_that(args.verbose).is_equal_to(0)

    def test_command_nargs_star_defaults_to_empty(self):
        args = create_parser().parse_args([])
        assert_that(args.command).is_equal_to([])


class TestMain:
    def _run(self, argv, conn=None):
        conn = conn or _make_conn()
        with (
            patch.object(sys, "argv", ["decker-cli"] + argv),
            patch("decker.cli.app.CliConnection", return_value=conn),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            return exc_info.value.code

    def test_no_command_exits_0(self):
        assert_that(self._run([])).is_equal_to(0)

    def test_help_alone_exits_0(self):
        assert_that(self._run(["help"])).is_equal_to(0)

    def test_list_command_exits_0(self, capsys):
        code = self._run(["list"])
        assert_that(code).is_equal_to(0)
        out = capsys.readouterr().out
        assert_that(out).contains("stop").contains("status")

    def test_help_subcommand_prints_description(self, capsys):
        code = self._run(["help", "status"])
        assert_that(code).is_equal_to(0)
        out = capsys.readouterr().out
        assert_that(out).contains("status").contains("Get status")

    def test_help_unknown_subcommand_exits_1(self, capsys):
        code = self._run(["help", "nonexistent"])
        assert_that(code).is_equal_to(1)

    def test_status_command_formats_dict(self, capsys):
        conn = _make_conn(request_return={"service_status": "running", "application_running": False})
        code = self._run(["status"], conn)
        assert_that(code).is_equal_to(0)
        out = capsys.readouterr().out
        assert_that(out).contains("service_status").contains("running")

    def test_stop_command_formats_bool_false(self, capsys):
        conn = _make_conn(request_return=False)
        code = self._run(["stop"], conn)
        assert_that(code).is_equal_to(0)
        assert_that(capsys.readouterr().out.strip()).is_equal_to("failed")

    def test_unknown_command_exits_1(self):
        conn = _make_conn()
        conn.request.side_effect = AttributeError("no such method")
        code = self._run(["nonexistent"], conn)
        assert_that(code).is_equal_to(1)

    def test_rpc_error_exits_2(self):
        conn = _make_conn()
        conn.request.side_effect = RuntimeError("server exploded")
        code = self._run(["status"], conn)
        assert_that(code).is_equal_to(2)

    def test_server_unreachable_exits_1(self):
        conn = _make_conn()
        conn.__enter__.side_effect = ConnectionRefusedError()
        code = self._run(["status"], conn)
        assert_that(code).is_equal_to(1)

    def test_host_override_reaches_connection(self):
        captured = {}

        def fake_cli_connection(host, port):
            captured["host"] = host
            captured["port"] = port
            return _make_conn()

        with (
            patch.object(sys, "argv", ["decker-cli", "--host", "myhost", "status"]),
            patch("decker.cli.app.CliConnection", side_effect=fake_cli_connection),
        ):
            with pytest.raises(SystemExit):
                main()
        assert_that(captured["host"]).is_equal_to("myhost")

    def test_port_override_reaches_connection(self):
        captured = {}

        def fake_cli_connection(host, port):
            captured["host"] = host
            captured["port"] = port
            return _make_conn()

        with (
            patch.object(sys, "argv", ["decker-cli", "--port", "9999", "status"]),
            patch("decker.cli.app.CliConnection", side_effect=fake_cli_connection),
        ):
            with pytest.raises(SystemExit):
                main()
        assert_that(captured["port"]).is_equal_to(9999)


class _FakeConn:
    def __init__(self, replies=None, error=None):
        self.calls = []
        self._replies = replies or {}
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def request(self, name, *args):
        self.calls.append((name, args))
        if self._error:
            raise self._error
        return self._replies.get(name)


def _run(argv, conn):
    with (
        patch.object(sys, "argv", ["decker-cli", *argv]),
        patch("decker.cli.app.CliConnection", return_value=conn),
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
    return exc_info.value.code


class TestPluginSubcommand:
    def test_app_routes_plugin_subcommands(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        conn = _FakeConn({"plugins_list": [{"id": "com.x.y", "version": "1.0.0", "name": "Y", "bundled": False}]})
        assert_that(_run(["plugin", "new", "com.x.y"], conn)).is_equal_to(0)
        assert_that(_run(["plugin", "pack", "com.x.y"], conn)).is_equal_to(0)
        package = tmp_path / "com.x.y-0.1.0.deckerplugin"
        assert_that(package.exists()).is_true()
        assert_that(conn.calls).is_empty()

        assert_that(_run(["plugin", "list"], conn)).is_equal_to(0)
        assert_that(capsys.readouterr().out).contains("com.x.y")
        conn2 = _FakeConn({"plugin_install": "job1"})
        assert_that(_run(["plugin", "install", str(package)], conn2)).is_equal_to(0)
        assert_that(capsys.readouterr().out).contains("Install started (job job1)")
        assert_that(conn2.calls[0][0]).is_equal_to("plugin_install")
        assert_that(_run(["plugin", "remove", "com.x.y"], conn2)).is_equal_to(0)
        assert_that(conn2.calls[-1]).is_equal_to(("plugin_uninstall", ("com.x.y",)))

    def test_plugin_list_empty(self, capsys):
        assert_that(_run(["plugin", "list"], _FakeConn({"plugins_list": []}))).is_equal_to(0)
        assert_that(capsys.readouterr().out).contains("No plugins installed")

    def test_plugin_install_permission_denied(self, capsys, tmp_path):
        package = tmp_path / "a.deckerplugin"
        package.write_bytes(b"x")
        assert_that(_run(["plugin", "install", str(package)], _FakeConn(error=PermissionError("no")))).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("only allowed from the server's own machine")

    def test_plugin_server_down(self, capsys):
        with (
            patch.object(sys, "argv", ["decker-cli", "plugin", "list"]),
            patch("decker.cli.app.CliConnection", side_effect=ConnectionRefusedError),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("cannot connect")

    def test_plugin_install_missing_path_exits_1(self):
        assert_that(_run(["plugin", "install"], _FakeConn())).is_equal_to(1)

    def test_plugin_new_pack_errors(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert_that(_run(["plugin", "new"], _FakeConn())).is_equal_to(1)
        assert_that(_run(["plugin", "new", "Bad_Id"], _FakeConn())).is_equal_to(1)
        assert_that(_run(["plugin", "pack"], _FakeConn())).is_equal_to(1)
        assert_that(_run(["plugin", "pack", "nope"], _FakeConn())).is_equal_to(1)

    def test_plugin_unknown_subcommand_exits_1(self, capsys):
        assert_that(_run(["plugin", "bogus"], _FakeConn())).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("unknown plugin subcommand")


class TestIconpackSubcommand:
    def test_iconpack_command_does_not_open_connection(self):
        with (
            patch.object(sys, "argv", ["decker-cli", "iconpack", "list"]),
            patch("decker.cli.app.CliConnection") as mock_conn_cls,
        ):
            with pytest.raises(SystemExit):
                main()
        mock_conn_cls.assert_not_called()

    def test_iconpack_no_subcommand_exits_1(self, capsys):
        with patch.object(sys, "argv", ["decker-cli", "iconpack"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("Usage")

    def test_iconpack_list_exits_0(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr("decker.asset.iconpack.iconpacks_dir", lambda: tmp_path / "iconpacks")
        monkeypatch.setattr("decker.asset.iconpack.IconPackStore", lambda: IconPackStore(tmp_path / "decker.db"))
        with patch.object(sys, "argv", ["decker-cli", "iconpack", "list"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(0)
        assert_that(capsys.readouterr().out).contains("No icon packs installed")

    def test_iconpack_install_missing_path_exits_1(self):
        with patch.object(sys, "argv", ["decker-cli", "iconpack", "install"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)

    def test_iconpack_install_invalid_source_exits_1(self, capsys, tmp_path):
        bad = tmp_path / "not-a-pack"
        bad.mkdir()
        with patch.object(sys, "argv", ["decker-cli", "iconpack", "install", str(bad)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("Error")

    def test_iconpack_remove_missing_uuid_exits_1(self):
        with patch.object(sys, "argv", ["decker-cli", "iconpack", "remove"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)

    def test_iconpack_remove_unknown_uuid_exits_1(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr("decker.asset.iconpack.iconpacks_dir", lambda: tmp_path / "iconpacks")
        with patch.object(sys, "argv", ["decker-cli", "iconpack", "remove", "unknown"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("Error")

    def test_iconpack_unknown_subcommand_exits_1(self, capsys):
        with patch.object(sys, "argv", ["decker-cli", "iconpack", "bogus"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("unknown iconpack subcommand")
