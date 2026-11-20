"""Request ids arrive as JSON of any type; a bad one must be a 400, never a 500."""

_MAX_ID = 2 ** 63 - 1


def parse_id(value):
    """Return value as a positive int, or None if it is not a usable database id."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if 0 < number <= _MAX_ID else None
