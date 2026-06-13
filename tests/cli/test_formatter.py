from assertpy import assert_that

from decker.cli.formatter import format_result


class TestFormatResult:
    def test_bool_true_returns_ok(self):
        assert_that(format_result(True)).is_equal_to("ok")

    def test_bool_false_returns_failed(self):
        assert_that(format_result(False)).is_equal_to("failed")

    def test_none_returns_placeholder(self):
        assert_that(format_result(None)).is_equal_to("(no output)")

    def test_string_returned_as_is(self):
        assert_that(format_result("hello")).is_equal_to("hello")

    def test_int_converted_to_string(self):
        assert_that(format_result(42)).is_equal_to("42")

    def test_dict_formats_key_value_pairs(self):
        result = format_result({"status": "running"})
        assert_that(result).contains("status").contains("running")

    def test_dict_float_formatted_to_three_decimals(self):
        result = format_result({"ts": 1.0})
        assert_that(result).contains("1.000")

    def test_dict_bool_true_formats_as_yes(self):
        result = format_result({"active": True})
        assert_that(result).contains("yes")

    def test_dict_bool_false_formats_as_no(self):
        result = format_result({"active": False})
        assert_that(result).contains("no")

    def test_dict_multiple_keys_each_on_own_line(self):
        result = format_result({"a": "1", "b": "2"})
        assert_that(result.split("\n")).is_length(2)

    def test_empty_list_returns_none_placeholder(self):
        assert_that(format_result([])).is_equal_to("(none)")

    def test_list_of_dicts_shows_indexed_blocks(self):
        result = format_result([{"type": "StreamDeck", "serial": "ABC"}])
        assert_that(result).contains("[0]").contains("type").contains("StreamDeck")

    def test_list_of_scalars_shows_indexed_items(self):
        result = format_result(["a", "b"])
        assert_that(result).contains("[0] a").contains("[1] b")

    def test_list_multiple_devices_each_gets_own_block(self):
        devices = [{"id": "1"}, {"id": "2"}]
        result = format_result(devices)
        assert_that(result).contains("[0]").contains("[1]")
