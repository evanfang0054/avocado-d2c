"""``python -m avocado`` entry point (used by the npm bin shim).

Why this file is needed: ``python3 -m avocado <args>`` requires the package
to have a ``__main__.py``, otherwise it errors with ``No module named
avocado.__main__``. Both the npm bin shim (packages/avocado/bin/avocado.sh)
and avocado installed via pipx/uv depend on this entry point.
"""

from avocado.cli import cli

if __name__ == "__main__":
    cli()
