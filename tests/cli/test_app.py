import sys
from argparse import ArgumentParser
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

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


class TestPluginSubcommand:
    def test_plugin_command_does_not_open_connection(self):
        with (
            patch.object(sys, "argv", ["decker-cli", "plugin", "list"]),
            patch("decker.cli.app.CliConnection") as mock_conn_cls,
        ):
            with pytest.raises(SystemExit):
                main()
        mock_conn_cls.assert_not_called()

    def test_plugin_list_exits_0(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr("decker.cli.plugin._PLUGINS_DIR", tmp_path / "plugins")
        with patch.object(sys, "argv", ["decker-cli", "plugin", "list"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(0)
        assert_that(capsys.readouterr().out).contains("No plugins installed")

    def test_plugin_install_missing_path_exits_1(self):
        with patch.object(sys, "argv", ["decker-cli", "plugin", "install"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)

    def test_plugin_unknown_subcommand_exits_1(self, capsys):
        with patch.object(sys, "argv", ["decker-cli", "plugin", "bogus"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert_that(exc_info.value.code).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains("unknown plugin subcommand")
