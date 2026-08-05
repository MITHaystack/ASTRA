"""
    astra-mqtt2db.py

    This software collects data from a set of MQTT telmetry streams which contain JSON 
    objects. The objects are assumed to be telemetry the antenna interface or the
    antenna motion controller. The time stamps are added prior to this point during the
    during the data collection process. The resulting objects are pushed into a MongoDB
    database as timeseries objects. For each object type an instantaneous state object
    is also maintained and updated when a new state change is detected. Logging from
    the MQTT log stream is also handled with options for both database and local
    logging via loguru. 

"""
import asyncio
import argparse
import os
import sys
import socket
import traceback
import json
from typing import Optional
import time

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger
import aiomqtt

from __future__ import annotations

from pymongo import AsyncMongoClient


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
class MongoDatabaseConfig:
    uri:         str = "mongodb://localhost:27017"
    db_name:     str = "astra"
    coll_name:   str = "telemetry"

    # Time series field names — must match create_collection() options
    time_field:  str = "timestamp"
    meta_field:  str = "meta"
    granularity: str = "seconds"    # "seconds" | "minutes" | "hours"

    # Default value written into meta.source when not supplied by caller
    meta_source: str = "astra"

    # In-memory fallback depth (1 week for 24h at 1 Hz)
    memory_len:  int = 604800


# ── client ────────────────────────────────────────────────────────────────────

class MotionHistoryClient:
    """
    Thread-safe (via asyncio.to_thread) motion history store.

    Typical lifecycle::

        client = MotionHistoryClient()
        await client.initialize()          # called from app.on_startup

        await client.record(az, alt, ...)  # called from simulation loop
        data = await client.query(3600)    # called from UI refresh timer
    """

    def __init__(self, config: MotionHistoryConfig | None = None) -> None:
        self.config  = config or MotionHistoryConfig()
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
              MongoDB ≥ 5.0 → create native time series collection.
              MongoDB < 5.0 → create regular collection + manual index.
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

    # ── document builder ──────────────────────────────────────────────────────

    def _make_ts_doc(
        self,
        az:       float,
        alt:      float,
        az_rate:  float,
        alt_rate: float,
        t:        datetime,
        source:   str = "",
    ) -> dict:
        """
        Build a MongoDB time series measurement document.

        The timeField value **must** be an aware datetime (UTC) so that MongoDB
        stores it as a proper BSON Date — never a string.
        """
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return {
            self.config.time_field: t,          # BSON Date
            self.config.meta_field: {            # static metadata (metaField)
                "source": source or self.config.meta_source,
                "system": "astra",
            },
            "az":       float(az),
            "alt":      float(alt),
            "az_rate":  float(az_rate),
            "alt_rate": float(alt_rate),
        }

    def _make_mem_doc(
        self,
        az:       float,
        alt:      float,
        az_rate:  float,
        alt_rate: float,
        t:        datetime,
    ) -> dict:
        """Minimal dict stored in the in-memory deque."""
        return {
            "timestamp": t,
            "az":        float(az),
            "alt":       float(alt),
            "az_rate":   float(az_rate),
            "alt_rate":  float(alt_rate),
        }

    # ── write ─────────────────────────────────────────────────────────────────

    async def record(
        self,
        az:       float,
        alt:      float,
        az_rate:  float = 0.0,
        alt_rate: float = 0.0,
        t:        Optional[datetime] = None,
        source:   str = "",
    ) -> None:
        """
        Record a single position sample.  Always updates the memory buffer
        synchronously (fast, runs in the event loop); MongoDB write is
        offloaded to the thread pool.
        """
        if t is None:
            t = datetime.now(timezone.utc)

        # Memory buffer updated immediately — no await, no thread hop
        self._memory.append(self._make_mem_doc(az, alt, az_rate, alt_rate, t))

        if self._use_db:
            doc = self._make_ts_doc(az, alt, az_rate, alt_rate, t, source)
            try:
                await asyncio.to_thread(self._coll.insert_one, doc)
            except Exception as exc:
                print(f"[history] insert_one error: {exc}")

    async def record_bulk(self, docs: list[dict]) -> None:
        """
        Bulk-insert a list of plain dicts (from history pre-population).

        Expected dict keys: ``t``, ``az``, ``alt``, ``az_rate``, ``alt_rate``.
        An optional ``source`` key is forwarded to the meta.source field.

        Uses ``ordered=False`` so a duplicate-key error on any single document
        does not abort the remainder of the batch.
        """
        if not docs:
            return

        # Update memory buffer (synchronous, event loop)
        for doc in docs:
            t = doc.get("t", datetime.now(timezone.utc))
            self._memory.append(
                self._make_mem_doc(
                    doc.get("az",       0.0),
                    doc.get("alt",      0.0),
                    doc.get("az_rate",  0.0),
                    doc.get("alt_rate", 0.0),
                    t,
                )
            )

        if self._use_db:
            ts_docs = [
                self._make_ts_doc(
                    az       = d.get("az",       0.0),
                    alt      = d.get("alt",      0.0),
                    az_rate  = d.get("az_rate",  0.0),
                    alt_rate = d.get("alt_rate", 0.0),
                    t        = d.get("t", datetime.now(timezone.utc)),
                    source   = d.get("source", ""),
                )
                for d in docs
            ]
            try:
                await asyncio.to_thread(
                    self._coll.insert_many, ts_docs, ordered=False
                )
            except Exception as exc:
                # BulkWriteError is expected when re-running (duplicate timestamps)
                print(f"[history] insert_many warning: {exc}")


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

"""
    Connects to the MQTT feed for telemetry from the ASTRA Antenna Interface. Pulls in the JSON
    telemetry objects and sends them to the telemetryQ for database ingestion. Telemetry is 
    handled as a time series database. 
"""
async def telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period):

    while True:
        if options.verbose:
            print("update telemetry mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/telemetry/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            tdata = json.loads(message.payload.decode('utf-8'))
                            await telemetryQ.put(tdata)
                        if options.verbose:
                            print("got telemetry: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                    status = {'event':'exception', 'source':'telemetry_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'telemetry_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'telemetry_mqtt_handler', 'value':f"dispatched {tdata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"telemetry loop global exception {err}")
            pass

        await asyncio.sleep(telemetry_period)

"""
    Connects to the MQTT feed for state information from the ASTRA Antenna Interface. Pulls in the JSON
    state objects and sends them to the stateQ for database ingestion. State information is treated as
    a updating object and not a time series. 
"""
async def state_mqtt_handler(options, stateQ, logQ, state_period):

    while True:
        if options.verbose:
            print("update state mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/state/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            sdata = json.loads(message.payload.decode('utf-8'))
                            await stateQ.put(sdata)
                        if options.verbose:
                            print("got state: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {state_period} seconds ...")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'state_mqtt_handler', 'value':f"dispatched {sdata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"state loop global exception {err}")
            pass

        await asyncio.sleep(state_period)

"""
    Connects to the MQTT feed for long information from the ASTRA Antenna Interface. Pulls in the JSON
    log objects and sends them to the logQ for loguru output. Long information is treated as a non
    database object but this allows for log centralization. 
"""
async def log_mqtt_handler(options, logQ, log_period):

    while True:
        if options.verbose:
            print("update log mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/state/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            ldata = json.loads(message.payload.decode('utf-8'))
                            await logQ.put(ldata)
                        if options.verbose:
                            print("got state: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {log_period} seconds ...")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'state_mqtt_handler', 'value':f"dispatched {ldata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"state loop global exception {err}")
            pass

        await asyncio.sleep(log_period)

""" 
    Accepts telemetry message objects from the telemtryQ and then adds them to the
    database as timeseries objects sorted by object type. 
"""
async def telemetry_db_handler(options, telemetryQ, logQ, telemetry_period):

    while True:

        if options.verbose:
            print("update telemetry db handler")

        try:
            tdata = telemetryQ.get_nowait()
            
            if tdata is not None:
                match tdata['event']:
                    case 'gps-data':
                        pass
                    case 'imu-data':
                        pass
                    case 'motion-data':
                        pass
                    case _:
                        if options.verbose:
                            print(f"unknown log event {msg}")
            else:
                tdata = None

            if options.verbose:
                print("telemetry object: ", tdata) 

        except Exception as e:
            if options.verbose:
                print(f"telemetry db exception {e}")
            else:
                pass

        await asyncio.sleep(telemetry_period)


""" 
    Accepts state message objects from the stateQ and then adds them to the
    database as updated objects sorted by object type. 
"""
async def state_db_handler(options, stateQ, logQ, state_period):

    while True:

        if options.verbose:
            print("update state db handler")

        try:
            sdata = stateQ.get_nowait()
            
            if sdata is not None:
                match sdata['event']:
                    case 'ai-display-state':
                        pass
                    case 'ai-diode-state':
                        pass
                    case 'ai-command-state':
                        pass
                    case _:
                        if options.verbose:
                            print(f"unknown log event {msg}")
            else:
                tdata = None

            if options.verbose:
                print("telemetry object: ", tdata) 

        except Exception as e:
            if options.verbose:
                print(f"state db exception {e}")
            else:
                pass

        await asyncio.sleep(state_period)


""" 
    Accepts log message objects from the logging Q and then outputs them sorted by
    log level to a loguru instance. Note there will be both local and remote timestamps. 
"""
async def log_handler(options, logQ, l_log, log_period):

    while True:

        if options.verbose:
            print("update log handler")

        try:
            ldata = logQ.get_nowait()
            
            if ldata is not None:
                msg = f"{ldata['source']({ldata['datetime_utc']}):ldata['value']}"
                match ldata['event']:
                    case 'exception' | 'error':
                        l_log.error(msg)
                    case 'warning':
                        l_log.warning(msg)
                    case 'status' | 'success':
                        l_log.success(msg)
                    case 'info':
                        l_log.info(msg)
                    case 'debug':
                        l_log.debug(msg)
                    case _:
                        if options.verbose:
                            print(f"unknown log event {msg}")
            else:
                ldata = None

            if options.verbose:
                print("log object: ", ldata) 

        except Exception as e:
            print(f"log handler exception {e}")

        await asyncio.sleep(log_period)



def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-mqtt2db.py"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Handle MQTT JSON object telemetry from the ASTRA antenna interface and send to database."
    desc = "\n".join(
        (
            "*" * width,
            "*{0:^{1}}*".format(title, width - 2),
            "*{0:^{1}}*".format(copyright, width - 2),
            "*{0:^{1}}*".format("", width - 2),
            "*{0:^{1}}*".format(shortdesc, width - 2),
            "*" * width,
        )
    )

    parser = argparse.ArgumentParser(
        description=desc,
        prefix_chars="-",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "-d",
        "--dbase",
        dest="database",
        default="mongodb://localhost:27017/",
        help=(
            "The MongoDB database used for storage of the telemetry timeseries and state."
        ),
    )
    
    parser.add_argument(
        "-m",
        "--mqtt",
        dest="mqtt",
        default="localhost",
        help=(
            "The mqtt device IP associated with the antenna interface unit streams."
        ),
    )

    parser.add_argument(
        "-l",
        "--log",
        dest="log",
        default=None,
        help=(
            "The path for loguru logging of the Log telemetry."
        ),
    ) 


    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="Makes the output information more verbose.",
    )

    options = parser.parse_args()

    return options



"""
    Primary Thread Startup 
"""
async def main():
    print("astra-mqtt2db startup")

    # Parse the Command Line for configuration
    options = parse_command_line()

    print("create async control")
    telemetryQ = asyncio.queue.Queue()
    stateQ = asyncio.queue.Queue()
    logQ = asyncio.queue.Queue()

    # create Database client
    db_client = AsyncMongoClient("mongodb://localhost:27017/")

    # create local logging
    print("setup logging")
    logger.remove()
    if options.log is not None:
        logger.add(f"{options.log}/astra-ai-mqtt.log", enqueue=True, level="INFO", rotation="8MB")

    print("set update periods")
    # set update periods in seconds
    log_period = 0.1
    telemetry_period = 0.1
    state_period = 0.1
     
    print("activate interfaces")
    telemetry_input_handler = telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period)
    state_input_handler = state_mqtt_handler(options, stateQ, logQ, state_period)
    log_input_handler = log_mqtt_handler(options,logQ,log_period)

    telemetry_update_handler = telemetry_db_handler(options,db_client,telemetryQ,logQ,telemetry_period)    
    state_update_handler = state_db_handler(options,,db_client,stateQ,logQ,state_period)    
    log_output_handler   = log_handler(options,logQ,logger,log_period)    
 
    print("setup asyncio tasks")
    clients = [asyncio.create_task(telemetry_input_handler)]
    clients.append(asyncio.create_task(state_input_handler))
    clients.append(asyncio.create_task(log_input_handler))
    clients.append(asyncio.create_task(telemetry_update_handler)) 
    clients.append(asyncio.create_task(state_update_handler))
    clients.append(asyncio.create_task(log_output_handler))
 
    print("run")

    await asyncio.gather(*clients)


asyncio.run(main())