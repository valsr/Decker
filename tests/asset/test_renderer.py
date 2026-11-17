import io

from assertpy import assert_that
from PIL import Image

from decker.asset.renderer import AssetRenderer

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'


def _png_bytes(size=(10, 10), color=(255, 0, 0, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _gif_bytes() -> bytes:
    frames = [Image.new("RGBA", (4, 4), (255, 0, 0, 255)), Image.new("RGBA", (4, 4), (0, 255, 0, 255))]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


class TestRenderPath:
    def test_renders_svg_file_at_target_size(self, tmp_path):
        path = tmp_path / "icon.svg"
        path.write_text(_SVG)
        image = AssetRenderer().render_path(path, 32, 48)
        assert_that(image.size).is_equal_to((32, 48))

    def test_renders_png_file_at_target_size(self, tmp_path):
        path = tmp_path / "icon.png"
        path.write_bytes(_png_bytes())
        image = AssetRenderer().render_path(path, 20, 20)
        assert_that(image.size).is_equal_to((20, 20))

    def test_renders_svg_at_multiple_sizes(self, tmp_path):
        path = tmp_path / "icon.svg"
        path.write_text(_SVG)
        renderer = AssetRenderer()
        assert_that(renderer.render_path(path, 16, 16).size).is_equal_to((16, 16))
        assert_that(renderer.render_path(path, 144, 144).size).is_equal_to((144, 144))


class TestRenderBytes:
    def test_renders_png_bytes(self):
        image = AssetRenderer().render_bytes(_png_bytes(), 24, 24)
        assert image is not None
        assert_that(image.size).is_equal_to((24, 24))

    def test_renders_svg_bytes(self):
        image = AssetRenderer().render_bytes(_SVG.encode(), 24, 24)
        assert image is not None
        assert_that(image.size).is_equal_to((24, 24))

    def test_renders_gif_first_frame_only(self):
        image = AssetRenderer().render_bytes(_gif_bytes(), 4, 4)
        assert image is not None
        assert_that(image.mode).is_equal_to("RGBA")

    def test_returns_none_for_unrecognized_bytes(self):
        image = AssetRenderer().render_bytes(b"not an image", 10, 10)
        assert_that(image).is_none()

    def test_returns_none_for_malformed_svg(self):
        image = AssetRenderer().render_bytes(b"<svg unterminated", 10, 10)
        assert_that(image).is_none()


class TestLimitsAndSniffing:
    def test_oversized_raster_is_rejected_before_decoding(self):
        import pytest

        from decker.asset.renderer import ImageTooLargeError

        data = _png_bytes(size=(5000, 5000))
        with pytest.raises(ImageTooLargeError):
            AssetRenderer().render_bytes(data, 10, 10)

    def test_svg_with_leading_comment_and_doctype_is_rendered(self):
        data = ("<!-- c -->\n<!DOCTYPE svg>\n" + _SVG).encode()
        image = AssetRenderer().render_bytes(data, 8, 8)
        assert_that(image).is_not_none()
        assert_that(image.size).is_equal_to((8, 8))
