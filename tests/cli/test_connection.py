from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.cli.connection import CliConnection


class TestCliConnection:
    def test_enter_calls_connect(self):
        mock_conn = MagicMock()
        with patch("rpyc.utils.factory.connect", return_value=mock_conn) as mock_connect:
            with CliConnection("localhost", 18861) as conn:
                mock_connect.assert_called_once()
                assert_that(conn).is_not_none()

    def test_exit_closes_connection(self):
        mock_conn = MagicMock()
        with patch("rpyc.utils.factory.connect", return_value=mock_conn):
            with CliConnection("localhost", 18861):
                pass
        mock_conn.close.assert_called_once()

    def test_exit_swallows_close_exception(self):
        mock_conn = MagicMock()
        mock_conn.close.side_effect = OSError("closed already")
        with patch("rpyc.utils.factory.connect", return_value=mock_conn):
            with CliConnection("localhost", 18861):
                pass  # should not raise

    def test_request_calls_remote_method(self):
        mock_conn = MagicMock()
        mock_conn.root.status.return_value = {"service_status": "running"}
        with patch("rpyc.utils.factory.connect", return_value=mock_conn):
            with CliConnection("localhost", 18861) as conn:
                result = conn.request("status")
        assert_that(result).contains_key("service_status")

    def test_request_raises_if_not_connected(self):
        conn = CliConnection("localhost", 18861)
        with pytest.raises(RuntimeError, match="context manager"):
            conn.request("status")

    def test_commands_converts_to_local_dict(self):
        mock_conn = MagicMock()
        mock_conn.root.commands.return_value = {
            "start": {"description": "Start", "return_type": "bool", "params": ""},
        }
        with patch("rpyc.utils.factory.connect", return_value=mock_conn):
            with CliConnection("localhost", 18861) as conn:
                result = conn.commands()
        assert_that(result).is_instance_of(dict)
        assert_that(result).contains_key("start")
        assert_that(result["start"]).contains_key("description")

    def test_connect_uses_configured_host_and_port(self):
        mock_conn = MagicMock()
        with patch("rpyc.utils.factory.connect", return_value=mock_conn) as mock_connect:
            with CliConnection("myhost", 9999):
                pass
        args = mock_connect.call_args
        assert_that(args[0][0]).is_equal_to("myhost")
        assert_that(args[0][1]).is_equal_to(9999)
