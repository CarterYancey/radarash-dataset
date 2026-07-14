"""SQL/path helpers shared by identity builders."""

import os
from pathlib import Path


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def atomic_replace(temporary: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, destination)
