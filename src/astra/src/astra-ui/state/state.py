"""
Global application state
========================
Lightweight dataclass singletons that are written by background asyncio
tasks and read by any NiceGUI page.

Because all writes and reads happen inside the same asyncio event loop
(NiceGUI timers run in the event loop; the aiomqtt subscriber task also
runs in the event loop) no locks are needed.

Usage::

    from astra.state import pointing

    az  = pointing.az
    alt = pointing.alt
    if pointing.is_fresh:
        ...
"""

from __future__ import annotations

import time
from datetime import datetime, UTC, timezone
from dataclasses import dataclass

from astradata.objects import *

@dataclass
class AstraState:
    """
        This represents the current state of the ASTRA system as known by the
        user interface. This is a shared representation used by the GUI for all
        display and update. 
            
            Major elements include 
            
            AstraAntennaState which is updated via MQTT
            AstraCommands which are sent via MQTT as JSON serialized dictionary objects
            UI state objects
            Configuration objects and information
            
    """
    
    last_update_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    antenna_state = AstraAntennaState()

    @property
    def age(self) -> float:
        """Seconds since last update; ∞ if never updated."""
        if self.last_update == 0.0:
            return float("inf")
        return time.time() - self.last_update

    @property
    def is_fresh(self) -> bool:
        """True when last update was within the last 10 seconds."""
        return self.age < 10.0


