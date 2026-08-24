"""Safe incremental cache for registered InsightFace embeddings."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CACHE_SCHEMA_VERSION = 1
MATCHING_FORMAT_VERSION = "raw-embedding-person-mean-v1"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class GalleryStats:
    persons: int
    images: int
    cached: int
    recomputed: int
    skipped: int
    valid_embeddings: int
    elapsed_ms: float
    cache_saved: bool


def recognition_fingerprint(model_root: Path, embedding_dimension: int = 512) -> dict:
    recognition_model = model_root / "w600k_r50.onnx"
    stat = recognition_model.stat() if recognition_model.exists() else None
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "model_pack": "buffalo_l",
        "recognition_model": recognition_model.name,
        "recognition_model_size": stat.st_size if stat else None,
        "recognition_model_mtime_ns": stat.st_mtime_ns if stat else None,
        "embedding_dimension": embedding_dimension,
        "matching_format": MATCHING_FORMAT_VERSION,
    }


def _scan(root: Path):
    images = []
    if not root.exists():
        return images
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES and ".cache" not in path.parts:
            relative = path.relative_to(root).as_posix()
            person = Path(relative).parts[0] if len(Path(relative).parts) > 1 else path.stem
            stat = path.stat()
            images.append((path, relative, person, stat.st_size, stat.st_mtime_ns))
    return images


def _load_cache(cache_path: Path, fingerprint: dict, warning: Callable[[str], None]):
    if not cache_path.exists():
        return {}
    try:
        with np.load(cache_path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"].item()))
            embeddings = np.asarray(archive["embeddings"], dtype=np.float32)
        if metadata.get("fingerprint") != fingerprint:
            return {}
        entries = metadata.get("entries", [])
        if len(entries) != len(embeddings):
            raise ValueError("metadata/embedding count mismatch")
        return {entry["relative_path"]: (entry, embeddings[index]) for index, entry in enumerate(entries)}
    except Exception as exc:
        warning(f"Corrupt/incompatible gallery cache ignored: {exc}")
        return {}


def _atomic_save(cache_path: Path, fingerprint: dict, entries: list[dict], embeddings: list[np.ndarray]):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_name(cache_path.name + f".{os.getpid()}.tmp")
    metadata = json.dumps({"fingerprint": fingerprint, "entries": entries}, separators=(",", ":"))
    matrix = (
        np.stack(embeddings).astype(np.float32)
        if embeddings
        else np.empty((0, fingerprint["embedding_dimension"]), dtype=np.float32)
    )
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, metadata=np.asarray(metadata), embeddings=matrix)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache_path)
    finally:
        temporary.unlink(missing_ok=True)


def build_gallery(
    root: Path, cache_path: Path, fingerprint: dict, extractor, rebuild=False, info=print, warning=print, progress=False
):
    started = time.perf_counter()
    images = _scan(root)
    cached_entries = {} if rebuild else _load_cache(cache_path, fingerprint, warning)
    entries, embeddings = [], []
    cached = recomputed = skipped = 0

    for index, (path, relative, person, size, mtime_ns) in enumerate(images, 1):
        cached_item = cached_entries.get(relative)
        if cached_item and cached_item[0].get("size") == size and cached_item[0].get("mtime_ns") == mtime_ns:
            entry, embedding = cached_item
            cached += 1
        else:
            if progress:
                info(f"[Identity Gallery] Building {index}/{len(images)}: {relative}")
            embedding, reason = extractor(path)
            if embedding is None:
                warning(f"[Identity Gallery][WARN] {relative} → {reason}, skipped")
                skipped += 1
                continue
            embedding = np.asarray(embedding, dtype=np.float32)
            if embedding.shape != (fingerprint["embedding_dimension"],) or not np.isfinite(embedding).all():
                warning(f"[Identity Gallery][WARN] {relative} → invalid embedding, skipped")
                skipped += 1
                continue
            entry = {"person": person, "relative_path": relative, "size": size, "mtime_ns": mtime_ns}
            recomputed += 1
        entries.append(entry)
        embeddings.append(embedding)

    changed = rebuild or recomputed > 0 or skipped > 0 or len(cached_entries) != len(entries)
    if changed:
        _atomic_save(cache_path, fingerprint, entries, embeddings)
    grouped = {}
    for entry, embedding in zip(entries, embeddings):
        grouped.setdefault(entry["person"], []).append(embedding)
    known = {person: np.mean(values, axis=0) for person, values in grouped.items()}
    stats = GalleryStats(
        persons=len(known),
        images=len(images),
        cached=cached,
        recomputed=recomputed,
        skipped=skipped,
        valid_embeddings=len(embeddings),
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        cache_saved=changed,
    )
    return known, stats
