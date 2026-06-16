from assertpy import assert_that

from decker.asset.resolver import AssetResolver


class TestAssetResolver:
    def test_resolves_svg_first(self, tmp_path):
        (tmp_path / "icon.svg").write_text("<svg/>")
        (tmp_path / "icon.png").write_bytes(b"png")
        result = AssetResolver().resolve(tmp_path / "icon")
        assert_that(result).is_equal_to(tmp_path / "icon.svg")

    def test_falls_back_to_png_when_no_svg(self, tmp_path):
        (tmp_path / "icon.png").write_bytes(b"png")
        (tmp_path / "icon@2x.png").write_bytes(b"png2x")
        result = AssetResolver().resolve(tmp_path / "icon")
        assert_that(result).is_equal_to(tmp_path / "icon.png")

    def test_falls_back_to_at_2x_png_when_no_plain_png(self, tmp_path):
        (tmp_path / "icon@2x.png").write_bytes(b"png2x")
        (tmp_path / "icon.jpg").write_bytes(b"jpg")
        result = AssetResolver().resolve(tmp_path / "icon")
        assert_that(result).is_equal_to(tmp_path / "icon@2x.png")

    def test_falls_back_to_jpg(self, tmp_path):
        (tmp_path / "icon.jpg").write_bytes(b"jpg")
        result = AssetResolver().resolve(tmp_path / "icon")
        assert_that(result).is_equal_to(tmp_path / "icon.jpg")

    def test_falls_back_to_jpeg_when_no_jpg(self, tmp_path):
        (tmp_path / "icon.jpeg").write_bytes(b"jpeg")
        result = AssetResolver().resolve(tmp_path / "icon")
        assert_that(result).is_equal_to(tmp_path / "icon.jpeg")

    def test_returns_none_when_nothing_matches(self, tmp_path):
        result = AssetResolver().resolve(tmp_path / "missing")
        assert_that(result).is_none()
