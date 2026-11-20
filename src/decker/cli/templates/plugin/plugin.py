"""A minimal Decker card: pressing the key changes its title."""

from decker_plugin_sdk import CardContext, DeckerPlugin, card


@card("{{card_id}}")
class Hello(DeckerPlugin):
    """Shows a greeting on the key when pressed."""

    def on_press(self, ctx: CardContext) -> None:
        ctx.set_title("Hello!")
