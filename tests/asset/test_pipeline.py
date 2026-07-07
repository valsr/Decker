from unittest.mock import MagicMock

from assertpy import assert_that
from PIL import Image

from decker.asset.pipeline import AssetPipeline, AssetResolutionRequest


def _make_pipeline(user_icon=None):
    store = MagicMock()
    store.get_user_icon.return_value = user_icon
    resolver = MagicMock()
    cache = MagicMock()
    cache.get.return_value = Image.new("RGBA", (1, 1))
    renderer = MagicMock()
    pipeline = AssetPipeline(store=store, resolver=resolver, cache=cache, renderer=renderer)
    return pipeline, store, resolver, cache, renderer


def _request(runtime_override=None, manifest_state_image=None, plugin_icon=None):
    return AssetResolutionRequest(
        context_id="ctx-1",
        width=10,
        height=10,
        runtime_override=runtime_override,
        manifest_state_image=manifest_state_image,
        plugin_icon=plugin_icon,
    )


class TestAssetPipelineFallbackChain:
    def test_runtime_override_wins_when_renderable(self):
        pipeline, _, _, _, renderer = _make_pipeline()
        rendered = Image.new("RGBA", (5, 5))
        renderer.render_bytes.return_value = rendered

        result = pipeline.resolve(_request(runtime_override=b"png-bytes"))

        assert_that(result).is_same_as(rendered)

    def test_falls_through_when_runtime_override_unrenderable(self, tmp_path):
        pipeline, store, _resolver, cache, renderer = _make_pipeline(user_icon=str(tmp_path / "user.svg"))
        renderer.render_bytes.return_value = None

        pipeline.resolve(_request(runtime_override=b"garbage"))

        store.get_user_icon.assert_called_once_with("ctx-1")
        cache.get.assert_called_once()

    def test_user_assigned_icon_used_when_no_runtime_override(self, tmp_path):
        user_path = tmp_path / "user.svg"
        pipeline, _store, resolver, cache, _ = _make_pipeline(user_icon=str(user_path))

        pipeline.resolve(_request())

        cache.get.assert_called_once_with(user_path, 10, 10)
        resolver.resolve.assert_not_called()

    def test_manifest_state_image_used_when_no_user_icon(self, tmp_path):
        pipeline, _store, resolver, cache, _ = _make_pipeline(user_icon=None)
        resolved_path = tmp_path / "state.svg"
        resolver.resolve.return_value = resolved_path

        pipeline.resolve(_request(manifest_state_image=tmp_path / "state"))

        cache.get.assert_called_once_with(resolved_path, 10, 10)

    def test_plugin_icon_used_when_state_image_unresolvable(self, tmp_path):
        pipeline, _store, resolver, cache, _ = _make_pipeline(user_icon=None)
        plugin_icon_resolved = tmp_path / "plugin.svg"
        resolver.resolve.side_effect = [None, plugin_icon_resolved]

        pipeline.resolve(_request(manifest_state_image=tmp_path / "state", plugin_icon=tmp_path / "plugin"))

        cache.get.assert_called_once_with(plugin_icon_resolved, 10, 10)

    def test_default_key_svg_used_when_nothing_else_resolves(self):
        pipeline, _store, resolver, cache, _ = _make_pipeline(user_icon=None)
        resolver.resolve.return_value = None

        pipeline.resolve(_request())

        from decker.asset.paths import (
            DEFAULT_KEY_SVG,  # pylint: disable=import-outside-toplevel
        )

        cache.get.assert_called_once_with(DEFAULT_KEY_SVG, 10, 10)
