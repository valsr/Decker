from unittest.mock import MagicMock

from assertpy import assert_that

from decker.server.plugins import _StreamDeckHardwareSink


def _make_sink(device_manager=None):
    labels: dict[tuple[str, int], str] = {}

    def _label_setter(device_id: str, key_index: int, label: str) -> None:
        labels[(device_id, key_index)] = label

    sink = _StreamDeckHardwareSink(device_manager=device_manager, label_setter=_label_setter)
    return sink, labels


class TestStreamDeckHardwareSink:
    def test_set_image_delegates_to_device_manager(self):
        dm = MagicMock()
        sink, _ = _make_sink(device_manager=dm)
        sink.set_image("dev1", 3, b"imgbytes")
        dm.set_image_bytes.assert_called_once_with("dev1", 3, b"imgbytes")

    def test_set_image_no_manager_does_not_raise(self):
        sink, _ = _make_sink(device_manager=None)
        sink.set_image("dev1", 0, b"imgbytes")  # should not raise

    def test_set_title_stores_label(self):
        sink, labels = _make_sink()
        sink.set_title("dev1", 2, "hello")
        assert_that(labels[("dev1", 2)]).is_equal_to("hello")

    def test_set_state_is_no_op(self):
        sink, _ = _make_sink()
        sink.set_state("dev", 0, 1)  # should not raise

    def test_show_alert_is_no_op(self):
        sink, _ = _make_sink()
        sink.show_alert("dev", 0)  # should not raise

    def test_show_ok_is_no_op(self):
        sink, _ = _make_sink()
        sink.show_ok("dev", 0)  # should not raise
