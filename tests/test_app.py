import argparse
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker_server.app import create_parser, handle_commands, main


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
            assert_that(parser._actions).is_not_empty()
            actions = {action.dest: action for action in parser._actions}
            assert_that(actions).contains_key("version")

        def test_create_parser_has_verbose_argument(self):
            # Tests if parser has verbose argument properly configured

            # Act
            parser = create_parser()

            # Assert
            actions = {action.dest: action for action in parser._actions}
            assert_that(actions).contains_key("verbose")
            assert_that(actions["verbose"].default).is_equal_to(0)

        def test_create_parser_has_dev_argument(self):
            # Tests if parser has dev mode argument properly configured

            # Act
            parser = create_parser()

            # Assert
            actions = {action.dest: action for action in parser._actions}
            assert_that(actions).contains_key("dev")
            assert_that(actions["dev"].dest).is_equal_to("dev")

    class TestHandleCommands:
        """Tests for the handle_commands function."""

        @patch("decker_server.command.config.list_config")
        def test_handle_config_list_command(self, mock_list_config):
            # Tests if handle_commands correctly calls list_config

            # Arrange
            args = MagicMock()
            args.keywords = ["test"]

            # Act
            handle_commands("config.list", args)

            # Assert
            mock_list_config.assert_called_once_with(["test"])

        @patch("decker_server.command.config.get_config")
        def test_handle_config_get_command(self, mock_get_config):
            # Tests if handle_commands correctly calls get_config

            # Arrange
            args = MagicMock()
            args.key = "test_key"

            # Act
            handle_commands("config.get", args)

            # Assert
            mock_get_config.assert_called_once_with("test_key")

        @patch("decker_server.command.config.set_config")
        def test_handle_config_set_command(self, mock_set_config):
            # Tests if handle_commands correctly calls set_config

            # Arrange
            args = MagicMock()
            args.key = "test_key"
            args.value = ["test", "value"]

            # Act
            handle_commands("config.set", args)

            # Assert
            mock_set_config.assert_called_once_with("test_key", "test value")

        @patch("decker_server.command.config.remove_config")
        def test_handle_config_remove_command(self, mock_remove_config):
            # Tests if handle_commands correctly calls remove_config

            # Arrange
            args = MagicMock()
            args.key = "test_key"

            # Act
            handle_commands("config.remove", args)

            # Assert
            mock_remove_config.assert_called_once_with("test_key")

        @patch("logging.error")
        def test_handle_invalid_command(self, mock_error):
            # Tests if handle_commands handles invalid commands correctly

            # Arrange
            args = MagicMock()

            # Act
            handle_commands("invalid.command", args)

            # Assert
            mock_error.assert_called_once()

    class TestMain:
        """Tests for the main function."""

        @patch("decker_server.app.InstanceManager")
        @patch("decker_server.logging.configure")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_configures_logging_with_different_verbosity(
            self, mock_parse_args, mock_configure, mock_instance_manager
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

        @patch("decker_server.app.InstanceManager")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_starts_server_without_command(self, mock_parse_args, mock_instance_manager):
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

        @patch("decker_server.app.InstanceManager")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_starts_server_with_dev_mode(self, mock_parse_args, mock_instance_manager):
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

        @patch("decker_server.app.handle_commands")
        @patch("argparse.ArgumentParser.parse_args")
        def test_main_handles_commands(self, mock_parse_args, mock_handle_commands):
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
