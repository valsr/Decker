import argparse
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.app import create_parser, main


class TestMain:
    """Tests for the __main__.py file."""

    class TestCreateParser:
        """Tests for the create_parser function."""

        def test_create_parser_returns_parser(self):
            # Tests if create_parser returns an ArgumentParser

            # Act
            parser = create_parser()

            # Assert
            assert_that(parser).is_instance_of(argparse.ArgumentParser)

        def test_create_parser_has_version_argument(self):
            # Tests if parser has version argument

            # Act
            parser = create_parser()

            # Assert
            assert_that(parser._actions).is_not_empty() # pylint: disable=protected-access
            actions = {action.dest: action for action in parser._actions}  # pylint: disable=protected-access
            assert_that(actions).contains_key("version")

        def test_create_parser_has_verbose_argument(self):
            # Tests if parser has verbose argument properly configured

            # Act
            parser = create_parser()

            # Assert
            actions = {action.dest: action for action in parser._actions} # pylint: disable=protected-access
            assert_that(actions).contains_key("verbose")
            assert_that(actions["verbose"].default).is_equal_to(0)

        def test_create_parser_has_dev_argument(self):
            # Tests if parser has dev mode argument properly configured

            # Act
            parser = create_parser()

            # Assert
            actions = {action.dest: action for action in parser._actions}  # pylint: disable=protected-access
            assert_that(actions).contains_key("dev")
            assert_that(actions["dev"].dest).is_equal_to("dev")

    class TestMain:
        """Tests for the main function."""

        @patch("decker.app.InstanceManager")
        @patch("decker.logging.configure")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_configures_logging_with_different_verbosity(
            self, mock_parse_args: MagicMock, mock_configure: MagicMock, _mock_instance_manager: MagicMock
        ):
            # Tests if main configures logging with the correct verbosity level

            # Arrange
            test_cases = [
                {"verbose": 0, "expected_level": 30},  # WARNING
                {"verbose": 1, "expected_level": 20},  # INFO
                {"verbose": 2, "expected_level": 10},  # DEBUG
            ]

            for test_case in test_cases:
                args = MagicMock()
                args.verbose = test_case["verbose"]
                args.command = None
                args.dev = False
                mock_parse_args.return_value = args

                # Act
                main()

                # Assert
                mock_configure.assert_called_with(level=test_case["expected_level"])

        @patch("decker.app.InstanceManager")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_starts_server_without_command(self, mock_parse_args: MagicMock, mock_instance_manager: MagicMock):
            # Tests if main starts server when no command is provided

            # Arrange
            args = MagicMock()
            args.command = None
            args.dev = False
            args.verbose = 0
            mock_parse_args.return_value = args
            instance = MagicMock()
            mock_instance_manager.return_value = instance

            # Act
            main()

            # Assert
            mock_instance_manager.assert_called_once_with(dev_mode=False)
            instance.start_server.assert_called_once()

        @patch("decker.app.InstanceManager")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_starts_server_with_dev_mode(self, mock_parse_args: MagicMock, mock_instance_manager: MagicMock):
            # Tests if main starts server with dev mode when specified

            # Arrange
            args = MagicMock()
            args.command = None
            args.dev = True
            args.verbose = 0
            mock_parse_args.return_value = args
            instance = MagicMock()
            mock_instance_manager.return_value = instance

            # Act
            main()

            # Assert
            mock_instance_manager.assert_called_once_with(dev_mode=True)

        @patch("decker.app.handle_commands")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_handles_commands(self, mock_parse_args: MagicMock, mock_handle_commands: MagicMock):
            # Tests if main handles commands when provided

            # Arrange
            args = MagicMock()
            args.command = "config"
            args.action = "list"
            args.verbose = 0
            mock_parse_args.return_value = args

            # Act
            main()

            # Assert
            mock_handle_commands.assert_called_once_with("config.list", args)
