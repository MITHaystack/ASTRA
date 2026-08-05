"""
astra.state
==========
Shared asyncio-native MQTT clients.

  state  — global state telemetry subscriber (aiomqtt)
"""

from .state import AstraState
from .subscriber import AstraStateSubscriber
from .commander import AstraStateCommander
from .history import AstraHistoryConfig, AstraHistoryClient

# ── Module-level singletons ────────────────────────────────────────────────────
# Import these anywhere with:  from astra.state import astra_state

# system state singleton
astra_state = AstraState()
astra_sub = AstraStateSubscriber(astra_state)

# system command singleton
astra_cmd = AstraStateCommander()

# database history singletons, one per history collection along with configurations
motion_history_cfg = AstraHistoryConfig()
motion_history_cfg.coll_name = "motion"
# Motion DB interface singleton
motion_history = AstraHistoryClient(motion_history_cfg)

imu_history_cfg = AstraHistoryConfig()
imu_history_cfg.coll_name = "imu"
# IMU DB interface singleton
imu_history = AstraHistoryClient(imu_history_cfg)

gps_history_cfg = AstraHistoryConfig()
gps_history_cfg.coll_name = "gps"
# GPS DB interface singleton
gps_history = AstraHistoryClient(gps_history_cfg)


