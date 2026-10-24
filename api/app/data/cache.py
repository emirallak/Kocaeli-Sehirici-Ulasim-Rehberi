"""Prebuilt snapshot cache that avoids parsing GTFS on every cold start.

Parsing ``stop_times`` and building indexes takes ~10 s; unpickling the
finished snapshot takes well under one second. The cache is valid only for
the exact GTFS files and loader source it was built from, so a stale file is
ignored rather than trusted. Rebuild with ``python -m api.app.data.cache``.
"""

from __future__ import annotations

import copyreg
import hashlib
import io
import logging
import lzma
import pickle
from pathlib import Path
from types import MappingProxyType

from api.app.data.loader import load_snapshot
from api.app.schemas.snapshot import RoutingSnapshot, read_only_mapping


logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent
RAW_DATA_DIR = DATA_DIR / "raw"
CACHE_PATH = DATA_DIR / "snapshot.pickle.xz"
_MAGIC = b"kocaeli-snapshot-v1 "
# Everything that shapes the pickled objects. A change here invalidates it.
_SOURCE_FILES = (
    DATA_DIR / "loader.py",
    DATA_DIR / "indexes.py",
    DATA_DIR / "geometry.py",
    DATA_DIR / "boarding_rules.py",
    DATA_DIR / "transport.py",
    DATA_DIR.parent / "schemas" / "snapshot.py",
)


def fingerprint(raw_dir: Path = RAW_DATA_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(raw_dir.iterdir()) + list(_SOURCE_FILES):
        if not path.is_file():
            continue
        content = path.read_bytes()
        if path.suffix != ".gz":
            # Git may check text out with CRLF on Windows and LF on Vercel.
            content = content.replace(b"\r\n", b"\n")
        digest.update(path.name.encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def read_cache(raw_dir: Path = RAW_DATA_DIR, cache_path: Path = CACHE_PATH) -> RoutingSnapshot | None:
    """Return the cached snapshot, or ``None`` when it is missing or stale."""

    try:
        with cache_path.open("rb") as source:
            header = source.readline().rstrip(b"\n")
            if header != _MAGIC + fingerprint(raw_dir).encode():
                logger.warning("Snapshot cache %s is stale; rebuilding from GTFS", cache_path)
                return None
            snapshot = pickle.loads(lzma.decompress(source.read()))
    except FileNotFoundError:
        return None
    except (OSError, EOFError, lzma.LZMAError, pickle.UnpicklingError, AttributeError, ImportError) as error:
        logger.warning("Snapshot cache %s is unreadable: %s", cache_path, error)
        return None
    return snapshot if isinstance(snapshot, RoutingSnapshot) else None


def write_cache(snapshot: RoutingSnapshot, raw_dir: Path = RAW_DATA_DIR, cache_path: Path = CACHE_PATH) -> None:
    buffer = io.BytesIO()
    pickler = pickle.Pickler(buffer, protocol=5)
    pickler.dispatch_table = copyreg.dispatch_table.copy()
    # MappingProxyType has no pickle support; rebuild it through the same
    # helper the loader uses.
    pickler.dispatch_table[MappingProxyType] = lambda proxy: (read_only_mapping, (dict(proxy),))
    pickler.dump(snapshot)
    payload = _MAGIC + fingerprint(raw_dir).encode() + b"\n" + lzma.compress(buffer.getvalue(), preset=6)
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(cache_path)


def load_cached_snapshot(raw_dir: Path = RAW_DATA_DIR, cache_path: Path = CACHE_PATH) -> RoutingSnapshot:
    """Load from the cache, falling back to GTFS and refreshing the cache."""

    snapshot = read_cache(raw_dir, cache_path)
    if snapshot is not None:
        return snapshot
    snapshot = load_snapshot(raw_dir)
    try:
        write_cache(snapshot, raw_dir, cache_path)
    except OSError as error:
        # Vercel's deployment filesystem is read-only; serving still works.
        logger.info("Snapshot cache not written: %s", error)
    return snapshot


if __name__ == "__main__":
    write_cache(load_snapshot(RAW_DATA_DIR))
    print(f"Wrote {CACHE_PATH} ({CACHE_PATH.stat().st_size / 1e6:.1f} MB)")
