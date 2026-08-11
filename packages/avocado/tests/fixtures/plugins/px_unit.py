"""Example plugin: adds 'px' to numeric style values that are missing units."""

from avocado.plugins.base import Plugin, hook


class PxUnitPlugin(Plugin):
    name = "px-unit-fixer"

    @hook("modify_style")
    def add_px(self, node, style):
        out = dict(style)
        for k, v in list(out.items()):
            # If value is a bare number (int/float) and prop is dimensional, add px
            if isinstance(v, (int, float)) and k in {
                "width",
                "height",
                "padding",
                "margin",
                "border-width",
                "border-radius",
                "gap",
            }:
                out[k] = f"{v}px"
        return out
