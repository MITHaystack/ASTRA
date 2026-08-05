"""
AstraStateSubscriber
==================
Reads telescope telemetry the MQTT broker using
the aiomqtt library and updates the global ``astra.state``
singleton.

"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, UTC, timezone
from dataclasses import dataclass, fields
from typing import Optional

from astradata.objects import *

# ── aiomqtt import guard ──────────────────────────────────────────────────────
_AIOMQTT_OK = False
try:
    import aiomqtt
    _AIOMQTT_OK = True
except ImportError:
    print("[AstraStateSubscriber] aiomqtt not installed")

# astra data types
import astradata

# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class AstraStateConfig:
    broker_host:        str   = "localhost"
    broker_port:        int   = 1883
    topic:              str  = "astra/motion/telemetry/#"
    connect_timeout:    float = 2.0    # seconds to wait for broker ACK
    reconnect_interval: float = 5.0   # seconds between reconnection attempts
    keepalive:          int   = 60

# ── subscriber ────────────────────────────────────────────────────────────────

class AstraStateSubscriber:
    """
    Persistent asyncio astra-telemetry subscriber.

    Typical lifecycle::

        # in app.on_startup:
        await astra_subscriber.start()

        # from a UI page:
        await astra_subscriber.configure("mybroker", 1883, "astra/antenna/telemetry")
    """


    def __init__(self, state, config: AstraStateConfig | None = None) -> None:
        self.config        = config or AstraStateConfig()
        self.state         = state
        self._task:        Optional[asyncio.Task] = None
        self._connected    = False
        self._running      = False
        self._msg_count  = 0

        self._client = None

    # ── public state ──────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> str:
        if self._connected:
            return f"● Live  {self.config.broker_host}:{self.config.broker_port}"
        return "○ Idle"

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background subscriber task."""
        if self._running:
            return
        self._running  = True
        self._task     = asyncio.create_task(
            self._run_loop(), name="astra-state-sub"
        )
        print(
            f"[AstraStateSubscriber] subscriber started  "
            f"({self.config.broker_host}:{self.config.broker_port}  "
            f"topic={self.config.topic})"
        )

    async def stop(self) -> None:
        """Cancel the background task and wait for it to finish."""
        self._running    = False
        self._connected  = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def configure(
        self,
        broker_host: str,
        broker_port: int,
        topic:       str,
    ) -> None:
        """Reconfigure broker / topic and restart the task immediately."""
        self.config.broker_host = broker_host
        self.config.broker_port = broker_port
        self.config.topic       = topic
        await self.stop()
        await self.start()
        print(
            f"[AstraStateSubscriber] reconfigured → "
            f"{broker_host}:{broker_port}  topic={topic}"
        )

    # ── connection to mqtt for inbound telemetry───────────────────────────────────────────────

    async def connect(self) -> tuple[bool, str]:
        
        if self._running and self._client is not None:
            return True, "running"
        
        self._loop = asyncio.get_running_loop()

        client = aiomqtt.Client(hostname=self.config.broker_host, port=self.config.broker_port, 
                                keepalive=self.config.keepalive)

        self._client = client
        self._running = True

        return True, (
            f"MQTT connected  ·  "
            f"{self.config.broker_host}:{self.config.broker_port}  ·  "
            f"tel={self.config.topic}"
        )


    async def disconnect(self) -> None:
        self._running    = False
        self._connected  = False
       
        if self._client:
            self._client = None
            pass

    # ── main task loop ────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """
        Outer reconnection loop.

        Tries MQTT → on failure attempts to reconnect → retries MQTT.
        """
        while self._running:
            connected = await self._try_mqtt()
            if not connected:
                await asyncio.sleep(1.0) # try to reconnect after a second
                await self.connect()

    # ── MQTT path ─────────────────────────────────────────────────────────────

    async def _try_mqtt(self) -> bool:
        """
        Attempt one MQTT session.  Returns True when the session ends
        cleanly (broker disconnected us); False if we could never connect.
        """
        #print("_try_mqtt")
        if not _AIOMQTT_OK:
            await asyncio.sleep(1)
            return False

        #print("_try_mqtt: check client")
        if self._client is None:
            return False

        try:
            #print("_try_mqtt: with client")

            async with self._client as client:
                self._connected  = True
                
                print(
                    f"[AstraStateSubscriber] MQTT connected  "
                    f"{self.config.broker_host}:{self.config.broker_port}"
                )

                #print("_try_mqtt: subscribe to topic <- ", self.config.topic)

                await client.subscribe(self.config.topic)
            
                #print("_try_mqtt: get messages")

                async for message in client.messages:
                    if not self._running:
                        return True

                    #print("_try_mqtt: go to _parse")
                    await self._parse(message)

            # Clean disconnect (broker closed the session)
            self._connected = False
            return True

        except Exception as exc:
            self._connected = False
            print(f"[AstraStateSubscriber] MQTT unavailable ({type(exc).__name__}: {exc})")
            return False

    async def _parse(self, message) -> None:
        """Parse an aiomqtt Message and update the global state."""
        try:
            payload = json.loads(message.payload.decode('utf-8'))

            match payload['event']:
                case 'telemetry':
                    match payload['group']:
                        case 'astra-calibration-data':
                            await self.state.antenna_state.update('astra-calibration',payload)
                        case 'astra-location-data':
                            await self.state.antenna_state.update('astra-location',payload)
                        case 'astra-offsets-data':
                            await self.state.antenna_state.update('astra-offsets',payload)
                        case 'astra-pointing-data':
                            await self.state.antenna_state.update('astra-pointing',payload)
                        case 'astra-sync-data':
                            await self.state.antenna_state.update('astra-sync',payload)
                        case 'astra-target-data':
                            await self.state.antenna_state.update('astra-target',payload)
                        case 'mount-encoder-data':
                            await self.state.antenna_state.update('mount-encoder',payload)
                        case 'mount-position-data':
                            await self.state.antenna_state.update('mount-position',payload)
                        case 'mount-rate-data':
                            await self.state.antenna_state.update('mount-rate',payload)
                        case 'mount-limits-data':
                            await self.state.antenna_state.update('mount-limits',payload)
                        case 'mount-az-mode-data':
                            await self.state.antenna_state.update('mount-mode-az',payload)
                        case 'mount-alt-mode-data':
                            await self.state.antenna_state.update('mount-mode-alt',payload)
                        case 'astra-imu-data':
                            await self.state.antenna_state.update('astra-imu',payload)
                        case 'astra-gps-data':
                            await self.state.antenna_state.update('astra-gps',payload)

                        case _:
                            print(f"[AstraStateSubscriber] unknown telemetry event {payload}")
                case _:
                    pass

        except Exception as exc:
            print(f"[AstraStateSubscriber] parse error: {exc}  payload={message.payload!r}")

