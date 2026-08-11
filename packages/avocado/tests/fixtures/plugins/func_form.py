"""Example plugin using module-level function form."""

from avocado.plugins.base import Plugin


class _MyPlugin(Plugin):
    name = "tag-prefixer"


# Hook registered via @hook decorator elsewhere — here just exists


def plugin():
    return _MyPlugin()
