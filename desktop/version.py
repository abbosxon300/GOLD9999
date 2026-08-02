from __future__ import annotations

import re


APP_VERSION = "1.0.6"

_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)$"
)


def parse_version(value: str) -> tuple[int, int, int]:
    normalized = str(value).strip()
    match = _VERSION_PATTERN.fullmatch(normalized)

    if match is None:
        raise ValueError(
            f"Noto‘g‘ri versiya: {value!r}"
        )

    return tuple(
        int(part)
        for part in match.groups()
    )


def is_newer_version(
    candidate: str,
    current: str = APP_VERSION,
) -> bool:
    return parse_version(candidate) > parse_version(current)


__all__ = [
    "APP_VERSION",
    "is_newer_version",
    "parse_version",
]
