import io
import logging
import time
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from PIL import Image

from decker.server.plugins import _StreamDeckHardwareSink
from tests.server.animation_fixture import (
    WRITER_THREAD,
    make_spec,
    opened_deck_manager,
    truncated_gif,
    wait_until,
)


def _make_sink(device_manager=None):
    labels: dict[tuple[str, int], str] = {}

    def _label_setter(device_id: str, key_index: int, label: str) -> None:
        labels[(device_id, key_index)] = label

    sink = _StreamDeckHardwareSink(device_manager=device_manager, label_setter=_label_setter)
    return sink, labels


def _png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (72, 72), color).save(buf, format="PNG")
    return buf.getvalue()


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


class TestSinkAnimations:
    """set_animation plays through a real DeviceManager over a fake deck and registers the spec for the GUI."""

    @pytest.fixture(name="opened")
    def opened_fixture(self, tmp_path):
        with opened_deck_manager(tmp_path) as opened:
            yield opened

    @staticmethod
    def _animate(sink, device_id: str, key_index: int, spec) -> None:
        sink.set_image(device_id, key_index, _png("red"))  # the poster first: a static write ends an animation
        sink.set_animation(device_id, key_index, spec)

    def test_sink_set_animation_records_spec_on_device_state(self, opened):
        dm, device_id, log = opened
        sink, _ = _make_sink(dm)
        spec = make_spec()

        self._animate(sink, device_id, 2, spec)

        state = dm.get_device_state(device_id)
        assert state is not None
        assert_that(state.get_key_animation(2)).is_equal_to(spec)
        assert_that(dm.animation_factory.spec_for(spec.animation_id)).is_equal_to(spec)
        assert_that(wait_until(lambda: len(log.for_key(2)) >= 3)).is_true()
        assert_that({write[2] for write in log.for_key(2)[1:]}).is_equal_to({WRITER_THREAD})

    def test_sink_set_image_after_an_animation_stops_it_and_forgets_it(self, opened):
        dm, device_id, log = opened
        sink, _ = _make_sink(dm)
        self._animate(sink, device_id, 2, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(2)) >= 3)).is_true()

        sink.set_image(device_id, 2, _png("blue"))
        time.sleep(0.15)  # a frame already under way may still land
        written = len(log.for_key(2))
        time.sleep(0.35)

        assert_that(len(log.for_key(2))).is_equal_to(written)
        state = dm.get_device_state(device_id)
        assert state is not None
        assert_that(state.get_key_animation(2)).is_none()

    def test_sink_set_animation_without_a_factory_still_plays(self):
        dm = MagicMock()
        dm.animation_factory = None
        sink, _ = _make_sink(dm)
        spec = make_spec()

        sink.set_animation("dev1", 1, spec)

        dm.set_animation.assert_called_once_with("dev1", 1, spec)

    def test_sink_set_animation_without_a_manager_does_not_raise(self):
        sink, _ = _make_sink(None)

        sink.set_animation("dev1", 1, make_spec())

    def test_truncated_gif_keeps_its_poster_warns_once_and_spares_other_keys(self, opened, caplog):
        dm, device_id, log = opened
        sink, _ = _make_sink(dm)
        broken = make_spec(truncated_gif())
        self._animate(sink, device_id, 5, make_spec())

        with caplog.at_level(logging.WARNING):
            self._animate(sink, device_id, 2, broken)
            self._animate(sink, device_id, 3, broken)  # the same GIF on a second key warns no more
            assert_that(dm.animation_factory.wait_idle(5.0)).is_true()
            time.sleep(0.2)
            key5 = len(log.for_key(5))
            time.sleep(0.3)

        assert_that(log.for_key(2)).is_length(1)  # the poster only
        assert_that(log.for_key(3)).is_length(1)
        assert_that(len(log.for_key(5))).is_greater_than(key5)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and broken.gif_sha[:12] in r.message]
        assert_that(warnings).is_length(1)
