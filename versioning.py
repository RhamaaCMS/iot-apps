"""Natural comparison for hardware revision labels such as rev2 and rev10."""

import re


def natural_version_key(value: str) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", (value or "").strip())
        if part
    )


def version_in_range(value: str, minimum: str = "", maximum: str = "") -> bool:
    key = natural_version_key(value)
    return (not minimum or key >= natural_version_key(minimum)) and (
        not maximum or key <= natural_version_key(maximum)
    )
