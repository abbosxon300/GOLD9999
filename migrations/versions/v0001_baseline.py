"""Register the existing production schema as migration baseline."""

VERSION = 1
NAME = "baseline_existing_schema"


def upgrade(connection) -> None:
    """
    Existing GOLD9999 installations already contain the current schema.

    This baseline intentionally performs no business-schema mutation.
    Future schema changes must be added as separate versioned migrations.
    """
    del connection
