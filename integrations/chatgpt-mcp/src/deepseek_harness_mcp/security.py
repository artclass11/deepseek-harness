from __future__ import annotations

import secrets


def is_valid_bearer(authorization: str | None, expected_token: str) -> bool:
    """Compare a single Bearer credential without timing-sensitive string equality."""
    if not authorization:
        return False
    scheme, separator, supplied = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not supplied:
        return False
    return secrets.compare_digest(supplied.strip(), expected_token)
