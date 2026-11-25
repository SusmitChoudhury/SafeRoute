"""
sim/logger.py – Simulation logger with colored levels, ring buffer, and file sink.

Log line format:
  [mm:ss.s] LEVEL   module    message

Levels and UI console colors:
  INFO   (blue)    - Normal progress, status updates
  CALC   (yellow)  - Numerical results from algorithms
  ROUTE  (green)   - Route planning and selection
  WARN   (orange)  - Data warnings, Warning 1 / Warning 2 events
  ALERT  (red)     - Danger zone detected or entered
  ERROR  (magenta) - Failures

Maintains a ring buffer of the last 500 lines for the UI side panel,
and appends every line to logs/run_<timestamp>.log.
"""

from collections import deque
from datetime import datetime
import os
from pathlib import Path
from typing import Optional

from config import LOG_RING_BUFFER_SIZE

# UI console color map (RGB) – modern high-contrast designer palette
LOG_COLORS = {
    "INFO":  (56, 189, 248),    # Sky blue (#38bdf8)
    "CALC":  (251, 191, 36),    # Amber gold (#fbbf24)
    "ROUTE": (52, 211, 153),    # Emerald (#34d399)
    "WARN":  (251, 146, 60),    # Bright orange (#fb923c)
    "ALERT": (248, 113, 113),   # Vibrant coral red (#f87171)
    "ERROR": (244, 114, 182),   # Pink magenta (#f472b6)
    "STEP":  (56, 189, 248),    # Pipeline step cyan (#38bdf8)
    "DONE":  (52, 211, 153),    # Pipeline done emerald (#34d399)
}


class SimLogger:
    """Live logging system with in-memory ring buffer and persistent file sink."""

    def __init__(self, log_dir: Optional[Path] = None, max_lines: int = LOG_RING_BUFFER_SIZE):
        self.max_lines = max_lines
        self.buffer: deque[tuple[str, str]] = deque(maxlen=max_lines)

        project_root = Path(__file__).resolve().parent.parent
        self.log_dir = Path(log_dir) if log_dir else project_root / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"run_{timestamp_str}.log"

        # Initialize file and keep handle open for sub-millisecond logging
        self._file = open(self.log_file, "a", encoding="utf-8", buffering=1)
        self._file.write(f"# SafeRoute Simulation Log - Started {datetime.now().isoformat()}\n")

    def __del__(self):
        try:
            if hasattr(self, "_file") and self._file:
                self._file.close()
        except Exception:
            pass

    def format_time(self, sim_time: float) -> str:
        """Format seconds into [mm:ss.s] timestamp string."""
        total_seconds = max(0.0, sim_time)
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"[{minutes:02d}:{seconds:04.1f}]"

    def log(self, level: str, module: str, msg: str, sim_time: float = 0.0) -> str:
        """Record a log message into the buffer and the log file.

        Args:
            level: 'INFO', 'CALC', 'ROUTE', 'WARN', 'ALERT', or 'ERROR'.
            module: Short name of originating module (e.g. 'router', 'lookahead').
            msg: Descriptive message text.
            sim_time: Current simulation time in seconds.

        Returns:
            str: Full formatted log line.
        """
        lvl = level.upper().ljust(8)
        mod = module.ljust(10)
        time_tag = self.format_time(sim_time)
        line = f"{time_tag} {lvl} {mod} {msg}"

        # Store in ring buffer
        self.buffer.append((level.upper(), line))

        # Append to open file handle (sub-millisecond)
        try:
            self._file.write(line + "\n")
        except Exception:
            pass

        return line

    def lines(self, n: Optional[int] = None) -> list[tuple[str, str]]:
        """Return the most recent log entries as (level, formatted_line) tuples."""
        if n is None or n >= len(self.buffer):
            return list(self.buffer)
        # Return last n entries
        return list(self.buffer)[-n:]

    def clear(self) -> None:
        """Clear the ring buffer."""
        self.buffer.clear()
