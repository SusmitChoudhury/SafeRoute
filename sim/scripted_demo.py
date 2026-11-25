"""
sim/scripted_demo.py – Scripted viva demonstration scenario (Seed 42).

Reproduces identical events on every execution:
  1. Starts walker from Law Gate in Walk mode.
  2. At sim time ~5.0 s (walker ~10-20 m), drops an accident ahead at (31.2550, 75.7043).
  3. Triggers Warning 1 at ~400 m look-ahead distance.
  4. Dynamic A* reroute calculates safer path avoiding the hazard.
  5. Displays Warning 2 banner and audio beep with extra distance (+m) and extra time (+min).
  6. Walker navigates the safe detour to the destination, logging summary metrics upon arrival.
"""

import random
from typing import Optional
import numpy as np

from config import DEFAULT_START_LATLON, DEFAULT_END_LATLON


class ScriptedDemoRunner:
    """Manages scheduled events for the deterministic viva demo."""

    def __init__(self, incident_trigger_time: float = 5.0):
        self.incident_trigger_time = incident_trigger_time
        self.incident_dropped = False
        self.incident_id: Optional[int] = None

    def update(self, sim) -> None:
        """Check scheduled timeline triggers during simulation update."""
        if not self.incident_dropped and sim.sim_time >= self.incident_trigger_time:
            self.incident_dropped = True
            # Drop accident ahead along the corridor (31.2550, 75.7043)
            self.incident_id = sim.drop_incident(31.2550, 75.7043, inc_type="accident")


_active_demo_runner: Optional[ScriptedDemoRunner] = None


def setup_scripted_demo(sim) -> None:
    """Initialize or reset simulation into the scripted demo scenario."""
    global _active_demo_runner

    # 1. Enforce deterministic random seeds
    random.seed(42)
    np.random.seed(42)

    # 2. Reset simulation
    sim.reset()
    sim.set_mode("walk")
    sim.set_time_scale(10)
    sim.set_detection_mode("lookahead")

    # 3. Attach demo runner to simulation update
    _active_demo_runner = ScriptedDemoRunner(incident_trigger_time=4.0)

    # Wrap sim.update to include the demo runner check
    original_update = sim.update

    def scripted_update(real_dt: float) -> None:
        original_update(real_dt)
        if _active_demo_runner:
            _active_demo_runner.update(sim)

    sim.update = scripted_update

    # 4. Start simulation moving
    sim.start_or_pause()
    sim.logger.log("INFO", "demo", "Scripted Demo initialized (seed=42, speed=x10)", sim.sim_time)

