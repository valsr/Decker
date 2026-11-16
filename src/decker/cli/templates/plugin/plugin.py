"""A minimal Decker action: pressing the key changes its title."""

from decker_plugin_sdk import ActionContext, DeckerPlugin, action


@action("{{action_id}}")
class Hello(DeckerPlugin):
    """Shows a greeting on the key when pressed."""

    def on_press(self, ctx: ActionContext) -> None:
        ctx.set_title("Hello!")
