"""
MotionHistoryClient — asyncio + MongoDB Time Series edition
============================================================
Uses MongoDB 5.0+ native time series collections
  (db = ``astra``,  collection = ``motion``).

Falls back transparently to a regular collection on MongoDB < 5.0,
and to an in-memory deque when the server is unreachable.

Time Series Collection spec
----------------------------
  timeField   : "timestamp"   – BSON Date (UTC), required
  metaField   : "meta"        – dict of static tags (source, system)
  granularity : "seconds"     – optimised for sub-minute writes

Measurement document written to MongoDB
----------------------------------------
::

    {
        "timestamp": ISODate("2026-07-17T14:32:00.500Z"),   # timeField
        "meta": {                                            # metaField
            "source": "simulation" | "hardware",
            "system": "astra"
        },
        "azimuth":       180.500,    # degrees
        "altitude":      45.250,     # degrees
        "az_rate":  +0.100,     # deg / s
        "alt_rate": -0.025      # deg / s
    }

Internal memory-buffer document (uniform with the MongoDB shape for query
normalisation)
::

    {
        "timestamp": datetime,
        "azimuth": float, "altitude": float, "az_rate": float, "alt_rate": float
    }

pymongo calls run in ``asyncio.to_thread`` — the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, UTC, timezone, timedelta
from typing import Optional

_PYMONGO_OK = False
try:
    import pymongo          # type: ignore
    _PYMONGO_OK = True
except ImportError:
    pass

# Minimum MongoDB version that supports time series collections
_TS_MIN_VERSION = (5, 0)


# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class AstraHistoryConfig:
    uri:         str = "mongodb://localhost:27017"
    db_name:     str = "astra"
    coll_name:   str = "unknown"

    # Time series field names — must match create_collection() options
    time_field:  str = "timestamp"
    meta_field:  str = "meta"
    granularity: str = "seconds"    # "seconds" | "minutes" | "hours"

    # Default value written into meta.source when not supplied by caller
    meta_source: str = "astra"

    # In-memory fallback depth (≈ 24 h at 1 Hz)
    memory_len:  int = 86400


# ── client ────────────────────────────────────────────────────────────────────

class AstraHistoryClient:
    """
    Thread-safe (via asyncio.to_thread) motion history store.

    Typical lifecycle::

        client = MotionHistoryClient()
        await client.initialize()          # called from app.on_startup

        await client.record(az, alt, ...)  # called from simulation loop
        data = await client.query(3600)    # called from UI refresh timer
    """

    def __init__(self, config: AstraHistoryConfig | None = None) -> None:
        self.config  = config or AstraHistoryConfig()
        self._memory: deque[dict] = deque(maxlen=self.config.memory_len)
        self._mongo  = None
        self._coll   = None
        self._use_db     = False
        self._ts_native  = False    # True → MongoDB ≥ 5.0 time series collection

    # ── initialisation ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """
        Probe MongoDB in the thread pool.  Safe to call from ``app.on_startup``.
        Sets ``_use_db`` and ``_ts_native`` before returning.
        """
        if not _PYMONGO_OK:
            print("[history] pymongo not installed — memory buffer only")
            return
        ok, ts_native = await asyncio.to_thread(self._connect_blocking)
        self._use_db    = ok
        self._ts_native = ts_native
        if ok:
            mode = "time series" if ts_native else "standard (MongoDB < 5.0)"
            print(f"[history] MongoDB connected ({mode}): {self.config.uri}")

    def _connect_blocking(self) -> tuple[bool, bool]:
        """
        1. Connect and detect MongoDB version.
        2. If the collection does not yet exist:
              MongoDB ≥ 5.0 → we need the mqtt2db service to create it, so log and wait...
              MongoDB < 5.0 → something is wrong as this is not expected.
        3. If the collection already exists, introspect its type.

        Returns (connected: bool, is_timeseries_native: bool).
        """
        try:
            client = pymongo.MongoClient(
                self.config.uri,
                serverSelectionTimeoutMS=2000,
            )
            info = client.server_info()
            self._mongo = client
            db  = client[self.config.db_name]
            cfg = self.config

            # ── version detection ─────────────────────────────────────────────
            major, minor = _parse_mongo_version(info.get("version", "0.0.0"))
            ts_supported = (major, minor) >= _TS_MIN_VERSION

            # ── collection setup ──────────────────────────────────────────────
            existing = db.list_collection_names()

            if cfg.coll_name not in existing:
                if ts_supported:
                    db.create_collection(
                        cfg.coll_name,
                        timeseries={
                            "timeField":   cfg.time_field,
                            "metaField":   cfg.meta_field,
                            "granularity": cfg.granularity,
                        },
                    )
                    ts_native = True
                    print(
                        f"[history] Created time series collection "
                        f"'{cfg.db_name}.{cfg.coll_name}' "
                        f"(timeField={cfg.time_field!r}, "
                        f"metaField={cfg.meta_field!r}, "
                        f"granularity={cfg.granularity!r})"
                    )
                else:
                    # Regular collection with a manual index on the time field
                    coll = db[cfg.coll_name]
                    coll.create_index([(cfg.time_field, pymongo.ASCENDING)])
                    ts_native = False
                    print(
                        f"[history] Created standard collection "
                        f"'{cfg.db_name}.{cfg.coll_name}' "
                        f"(MongoDB {major}.{minor} < 5.0 — "
                        f"time series not supported)"
                    )
            else:
                # Introspect the existing collection's options
                coll_list = list(
                    db.list_collections(filter={"name": cfg.coll_name})
                )
                ts_native = bool(
                    coll_list
                    and coll_list[0].get("options", {}).get("timeseries")
                )

            self._coll = db[cfg.coll_name]
            return True, ts_native

        except Exception as exc:
            print(f"[history] MongoDB unavailable: {exc}")
            return False, False

    # ── public properties ─────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._use_db

    @property
    def is_timeseries(self) -> bool:
        """True when the collection is a native MongoDB time series collection."""
        return self._ts_native

    @property
    def backend(self) -> str:
        """Human-readable backend label for UI status badges."""
        if not self._use_db:
            return "Memory"
        return "MongoDB TS" if self._ts_native else "MongoDB"

    # ── read ──────────────────────────────────────────────────────────────────

    async def query(self, fields: dict, duration_s: float) -> dict:
        """
        Return the last *duration_s* seconds of motion history as a
        dict-of-lists suitable for direct Plotly chart update::

            {"t": [...], "az": [...], "alt": [...],
             "az_rate": [...], "alt_rate": [...]}

        Primary: MongoDB time series range query on timeField.
        Fallback: scan the in-memory deque.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=duration_s)

        if self._use_db:
            try:
                docs = await asyncio.to_thread(self._query_blocking, fields, cutoff)
                if docs:
                    return _to_arrays(docs)
            except Exception as exc:
                print(f"[history] query error: {exc}")

        # Memory fallback
        mem_docs = [d for d in self._memory if d["timestamp"] >= cutoff]
        return _to_arrays_mem(mem_docs)

    def _query_blocking(self, fields: dict, cutoff: datetime) -> list[dict]:
        """
        Blocking MongoDB range query — runs in thread pool.

        For a time series collection MongoDB automatically uses the timeField
        index (a clustered index on BSON Date).  No hint() required.

        Projection excludes _id and the metaField (not needed for plotting).
        The timeField is renamed to "timestamp" in the returned dicts for
        uniform downstream handling regardless of its configured name.

        Fields are a dict with an 1 / 0 indicator to return them. 
            {
            "az":      1,
            "alt":     1,
            "az_rate": 1,
            "alt_rate":1,
            }

        """
        tf    = self.config.time_field
        mf    = self.config.meta_field
        proj  = {
            "_id":   0,
            tf:      1,
            mf:      0,   # exclude meta tags — not needed for plots
        }
        # add the supplied fields to the database query
        # are are assuming we always want ascending time series from the time cursor point
        proj |= fields
        # align the time cursor point
        cursor = (
            self._coll
            .find({tf: {"$gte": cutoff}}, proj)
            .sort(tf, pymongo.ASCENDING)
            .limit(20_000)
        )
        docs: list[dict] = []
        for doc in cursor:
            # Normalise: if timeField key name differs from "timestamp"
            # rename it so _to_arrays works uniformly.
            if tf != "timestamp" and tf in doc:
                doc["timestamp"] = doc.pop(tf)
            docs.append(doc)
        return docs


# ── module helpers ─────────────────────────────────────────────────────────────

def _parse_mongo_version(version_str: str) -> tuple[int, int]:
    """Parse "5.0.14" → (5, 0).  Tolerates unexpected formats."""
    parts = version_str.split(".")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 0, 0


def _to_arrays(docs: list[dict]) -> dict:
    """Convert a list of MongoDB documents (with 'timestamp' key) to dict-of-lists."""
    if not docs:
        return _empty_arrays()
    return {
        "t":        [
            d["timestamp"].isoformat()
            if isinstance(d["timestamp"], datetime)
            else str(d["timestamp"])
            for d in docs
        ],
        "az":       [d.get("az",       0.0) for d in docs],
        "alt":      [d.get("alt",      0.0) for d in docs],
        "az_rate":  [d.get("az_rate",  0.0) for d in docs],
        "alt_rate": [d.get("alt_rate", 0.0) for d in docs],
    }


def _to_arrays_mem(docs: list[dict]) -> dict:
    """Convert a list of memory-buffer dicts (with 'timestamp' key) to dict-of-lists."""
    if not docs:
        return _empty_arrays()
    return {
        "t":        [
            d["timestamp"].isoformat()
            if isinstance(d["timestamp"], datetime)
            else str(d["timestamp"])
            for d in docs
        ],
        "az":       [d.get("az",       0.0) for d in docs],
        "alt":      [d.get("alt",      0.0) for d in docs],
        "az_rate":  [d.get("az_rate",  0.0) for d in docs],
        "alt_rate": [d.get("alt_rate", 0.0) for d in docs],
    }


def _empty_arrays() -> dict:
    t = datetime.now(timezone.utc).isoformat()
    return {"t": [t], "az": [0.0], "alt": [0.0],
            "az_rate": [0.0], "alt_rate": [0.0]}