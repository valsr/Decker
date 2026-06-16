from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.common.api import ApiHandler


class TestApiHandler:
    def test_request_connects_and_calls_remote_function(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.return_value = {"status": "healthy"}
        with patch("decker.common.api.rpyc.utils.factory.connect", return_value=mock_conn):
            api = ApiHandler()
            result = api.request("heartbeat")
        assert result is not None
        assert_that(result["status"]).is_equal_to("healthy")

    def test_request_reuses_existing_connection(self):
        mock_conn = MagicMock()
        mock_conn.root.status.return_value = {}
        with patch("decker.common.api.rpyc.utils.factory.connect", return_value=mock_conn) as mock_connect:
            api = ApiHandler()
            api.request("status")
            api.request("status")
        assert_that(mock_connect.call_count).is_equal_to(1)

    def test_request_raises_on_connection_failure(self):
        with patch("decker.common.api.rpyc.utils.factory.connect", side_effect=ConnectionRefusedError("refused")):
            api = ApiHandler()
            try:
                api.request("heartbeat")
                assert False, "expected exception"
            except ConnectionRefusedError:
                pass

    def test_del_closes_connection(self):
        mock_conn = MagicMock()
        with patch("decker.common.api.rpyc.utils.factory.connect", return_value=mock_conn):
            api = ApiHandler()
            api.request("heartbeat")
        api.__del__()
        mock_conn.close.assert_called_once()
