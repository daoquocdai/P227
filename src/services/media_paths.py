from pathlib import Path

SNAPSHOT_ROOT = (Path.cwd() / "snapshots").resolve()
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def valid_snapshot_name(value: str | None) -> str | None:
    if not value:
        return None
    name = Path(value).name
    if not name or Path(name).suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        return None
    candidate = (SNAPSHOT_ROOT / name).resolve()
    if candidate.parent != SNAPSHOT_ROOT or not candidate.is_file():
        return None
    return name


def snapshot_url(value: str | None) -> str | None:
    name = valid_snapshot_name(value)
    return None if name is None else f"/snapshots/{name}"
