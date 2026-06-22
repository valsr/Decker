"""Tests for decker.server.app."""

import argparse
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.server.app import create_parser, main


class TestCreateParser:
    def test_returns_argument_parser(self):
        assert_that(create_parser()).is_instance_of(argparse.ArgumentParser)

    def test_has_version_argument(self):
        actions = {a.dest: a for a in create_parser()._actions}  # pylint: disable=protected-access
        assert_that(actions).contains_key("version")

    def test_has_verbose_argument(self):
        actions = {a.dest: a for a in create_parser()._actions}  # pylint: disable=protected-access
        assert_that(actions).contains_key("verbose")
        assert_that(actions["verbose"].default).is_equal_to(0)


class TestMain:
    @patch("decker.server.app.ServerMonitor")
    @patch("decker.common.logging.configure")
    @patch("argparse.ArgumentParser.parse_args")
    def test_configures_logging_verbosity(
        self,
        mock_parse_args: MagicMock,
        mock_configure: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        mock_monitor_cls.return_value.start.return_value = None
        mock_monitor_cls.return_value.stop.return_value = None

        for verbose, expected_level in [(0, 30), (1, 20), (2, 10)]:
            args = MagicMock()
            args.verbose = verbose
            mock_parse_args.return_value = args
            main()
            mock_configure.assert_called_with(
                level=expected_level, log_directory=mock_configure.call_args[1]["log_directory"]
            )

    @patch("decker.server.app.ServerMonitor")
    @patch("argparse.ArgumentParser.parse_args")
    def test_starts_and_stops_monitor(self, mock_parse_args: MagicMock, mock_monitor_cls: MagicMock) -> None:
        args = MagicMock()
        args.verbose = 0
        mock_parse_args.return_value = args
        instance = MagicMock()
        mock_monitor_cls.return_value = instance

        main()

        instance.start.assert_called_once()
        instance.stop.assert_called_once()

    @patch("decker.server.app.ServerMonitor")
    @patch("argparse.ArgumentParser.parse_args")
    def test_stop_called_even_on_exception(self, mock_parse_args: MagicMock, mock_monitor_cls: MagicMock) -> None:
        args = MagicMock()
        args.verbose = 0
        mock_parse_args.return_value = args
        instance = MagicMock()
        instance.start.side_effect = RuntimeError("boom")
        mock_monitor_cls.return_value = instance

        main()

        instance.stop.assert_called_once()
