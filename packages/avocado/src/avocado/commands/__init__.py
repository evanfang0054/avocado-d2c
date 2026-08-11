"""avocado CLI subcommand module.

Each subcommand exports an independent ``run_*_command()`` function; cli.py
routes them through a click.group.

Module organization (KISS):
- ``gen`` — the original cli.py main logic (keeps original behavior; can be split later)
- ``schema`` — introspects all commands/flags/error codes (source of truth: this module + envelope.ERROR_CODES)
"""
