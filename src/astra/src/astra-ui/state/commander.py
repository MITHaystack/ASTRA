"""
AstraStateCommander
==================
Reads telescope telemetry from anb MQTT broker using
the aiomqtt library and updates the global ``astra.state``
singleton.

"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, UTC, timezone
from dataclasses import dataclass, fields
from typing import Optional

# ASTRA data objects
import astradata

# ── aiomqtt import guard ──────────────────────────────────────────────────────
_AIOMQTT_OK = False
try:
    import aiomqtt
    _AIOMQTT_OK = True
except ImportError:
    print("[AstraStateCommander] aiomqtt not installed")

# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class AstraStateCommandConfig:
    broker_host:        str   = "localhost"
    broker_port:        int   = 1883
    topic:              str  = "astra/motion/command"
    connect_timeout:    float = 5.0    # seconds to wait for broker ACK
    reconnect_interval: float = 30.0   # seconds between reconnection attempts
    keepalive:          int   = 60
    verbose:            bool = True

# -- command source 
class AstraStateCommander:
    """
        Persistent asyncio astra-command source. Provides message helper functions
        for generating properly formatted command objects.s

    """
    def __init__(self, config: AstraStateCommandConfig | None = None) -> None:
        self.config        = config or AstraStateCommandConfig()
        self._task:        Optional[asyncio.Task] = None
        self._connected    = False
        self._running      = False

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
        """Start the background mqtt command task."""
        if self._running:
            return
        self._running  = True
        self._task     = asyncio.create_task(
            self._run_loop(), name="astra-state-cmd"
        )
        print(
            f"[AstraStateCommander] mqtt command task started  "
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
            f"[AstraStateCommander] reconfigured → "
            f"{broker_host}:{broker_port}  topic={topic}"
        )


    # ── connection to mqtt for outgoing commands───────────────────────────────────────────────

    async def connect(self) -> tuple[bool, str]:
        if self._running:
            return True, "running"
        self._loop = asyncio.get_running_loop()

        self._client = aiomqtt.Client(hostname=self.config.broker_host, port=self.config.broker_port, 
                                keepalive=self.config.keepalive)

        print(f"client is {self._client}")

        self._running = True

        return True, (
            f"MQTT connected  ·  "
            f"{self.config.broker_host}:{self.config.broker_port}  ·  "
            f"cmd={self.config.topic}"
        )


    async def disconnect(self) -> None:
        self._running    = False
        self._connected  = False
       
        if self._client:
            self._client = None
            pass # aiomqtt already disconnected here 

    # ── main task loop ────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """
        Outer reconnection loop.

        Tries MQTT → on failure attempts to reconnect → retries MQTT.
        """
        while self._running:
            if not self._connected or self._client is None:
                await asyncio.sleep(1.0) # try to reconnect after a second
                await self.connect()
            else:
                await asyncio.sleep(0.1)


    # ── command publisher ────────────────────────────────────────────────────
    # async safe to call from event-loop button handlers.

    def _validate_command(self,cmd,dclass):
        return astradata.objects.validate_command(cmd,dclass)

    async def _publish(self, obj, chan) -> None:

        print(f"publish object {obj}")
        # locked object serialization to JSON
        payload = await astradata.objects.serialize(obj)

        try:
            
            async with aiomqtt.Client(hostname=self.config.broker_host, port=self.config.broker_port, 
                                                keepalive=self.config.keepalive) as self._client:
                print("async publish call")
                if chan is None:
                    await self._client.publish(self.config.topic, payload=payload)
                else:
                    await self._client.publish(chan, payload=payload)

                if self.config.verbose:
                    print(f"command object of type {obj.group} sent to mqtt")

        except aiomqtt.MqttError as err:
            #if self.config.verbose:
            print(f"Connection lost; Reconnect attempt after 1 second ...")
            
            status = {'event':'error', 'source':'ui state commander', 'value':f"mqtt connection lost {err}"}

            # place holder for logging
            print(status)

            await asyncio.sleep(1)
        except Exception as e:
            print(f"ui state _publish command exception {e}")

    async def send(self, cmd, dclass, chan=None) -> None:
        self._validate_command(cmd,dclass)
        await self._publish(cmd,chan)

