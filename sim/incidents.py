"""
sim/incidents.py – SQLite-backed incident store.

Implements the SQLite storage schema specified in Section 9.1:
  - Loads seed incidents from data/incidents_seed.csv on startup.
  - Supports live click-to-drop and removal of incidents.
  - Automatically transforms WGS84 coordinates (lat, lon) to UTM (x, y)
    for accurate distance calculations in the risk model.
"""

import csv
from datetime import datetime
import os
from pathlib import Path
import sqlite3
from typing import Optional

import pyproj

from config import INCIDENT_TYPES
from core.risk_model import Incident

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "saferoute.db"
SEED_CSV_PATH = PROJECT_ROOT / "data" / "incidents_seed.csv"

# Cached pyproj transformer from WGS84 to UTM (Zone 43N default for Punjab)
_TRANSFORMER_4326_TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


class IncidentStore:
    """Manages persistence and retrieval of simulation incidents via SQLite."""

    def __init__(self, db_path: Optional[Path] = None, graph_crs: str = "EPSG:32643"):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.graph_crs = graph_crs
        self.transformer = (
            _TRANSFORMER_4326_TO_UTM
            if graph_crs == "EPSG:32643"
            else pyproj.Transformer.from_crs("EPSG:4326", graph_crs, always_xy=True)
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.load_seed_if_empty()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the incidents table if it does not exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    type        TEXT    NOT NULL CHECK (type IN
                                ('accident','flooding','unsafe_area','construction','road_damage')),
                    lat         REAL    NOT NULL,
                    lon         REAL    NOT NULL,
                    severity    INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5),
                    radius_m    REAL    NOT NULL,
                    blocking    INTEGER NOT NULL DEFAULT 0,
                    source      TEXT    NOT NULL CHECK (source IN ('historical','live','simulated')),
                    created_at  TEXT    NOT NULL,
                    active      INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            conn.commit()

    def load_seed_if_empty(self) -> int:
        """Populate database from data/incidents_seed.csv if table is empty.

        Returns:
            int: Number of seed incidents loaded.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM incidents")
            count = cursor.fetchone()[0]
            if count > 0:
                return count

        if not SEED_CSV_PATH.exists():
            return 0

        inserted = 0
        with self._get_connection() as conn:
            with open(SEED_CSV_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    conn.execute(
                        """
                        INSERT INTO incidents (type, lat, lon, severity, radius_m, blocking, source, created_at, active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["type"],
                            float(row["lat"]),
                            float(row["lon"]),
                            int(row["severity"]),
                            float(row["radius_m"]),
                            int(row["blocking"]),
                            row["source"],
                            row["created_at"],
                            int(row["active"]),
                        ),
                    )
                    inserted += 1
            conn.commit()
        return inserted

    def add_incident(
        self,
        inc_type: str,
        lat: float,
        lon: float,
        severity: Optional[int] = None,
        radius_m: Optional[float] = None,
        blocking: Optional[bool] = None,
        source: str = "live",
    ) -> int:
        """Add a new incident to SQLite and return its assigned ID.

        Args:
            inc_type: One of ('accident','flooding','unsafe_area','construction','road_damage').
            lat: Latitude.
            lon: Longitude.
            severity: 1-5 (defaults to standard type config if None).
            radius_m: Danger radius in metres (defaults to type config if None).
            blocking: Whether road closes for vehicles (defaults to type config if None).
            source: 'live', 'simulated', or 'historical'.

        Returns:
            int: ID of inserted incident.
        """
        conf = INCIDENT_TYPES.get(inc_type, INCIDENT_TYPES["accident"])
        sev = severity if severity is not None else conf["severity"]
        rad = radius_m if radius_m is not None else conf["radius_m"]
        blk = 1 if (blocking if blocking is not None else conf["blocking"]) else 0
        now_str = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO incidents (type, lat, lon, severity, radius_m, blocking, source, created_at, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (inc_type, lat, lon, sev, rad, blk, source, now_str),
            )
            conn.commit()
            return cursor.lastrowid

    def remove_incident(self, incident_id: int) -> bool:
        """Mark an incident as inactive (deactivated).

        Args:
            incident_id: ID of the incident to remove.

        Returns:
            bool: True if an incident was updated.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE incidents SET active = 0 WHERE id = ?", (incident_id,))
            conn.commit()
            return cursor.rowcount > 0

    def move_incident(self, incident_id: int, lat: float, lon: float) -> bool:
        """Update the geographic coordinates of an active incident (supports live drag and drop).

        Args:
            incident_id: ID of the incident being repositioned.
            lat: New latitude.
            lon: New longitude.

        Returns:
            bool: True if the record was updated.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE incidents SET lat = ?, lon = ? WHERE id = ?",
                (float(lat), float(lon), int(incident_id)),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_live_incidents(self) -> int:
        """Deactivate all live-dropped incidents, leaving historical seed data intact.

        Returns:
            int: Number of incidents deactivated.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE incidents SET active = 0 WHERE source = 'live'")
            conn.commit()
            return cursor.rowcount

    def get_active_incidents(self) -> list[Incident]:
        """Fetch all active incidents with coordinates projected to UTM.

        Returns:
            list[Incident]: Ready for distance calculations in the risk model.
        """
        now = datetime.now()
        incidents = []

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, type, lat, lon, severity, radius_m, blocking, source, created_at
                FROM incidents
                WHERE active = 1
                ORDER BY id ASC
                """
            )
            rows = cursor.fetchall()

        for row in rows:
            lat = float(row["lat"])
            lon = float(row["lon"])
            utm_x, utm_y = self.transformer.transform(lon, lat)

            # Calculate age in days
            try:
                created_dt = datetime.fromisoformat(row["created_at"])
                age_days = max(0.0, (now - created_dt).total_seconds() / 86400.0)
            except Exception:
                age_days = 0.0

            inc = Incident(
                id=int(row["id"]),
                type=row["type"],
                x=float(utm_x),
                y=float(utm_y),
                severity=int(row["severity"]),
                radius_m=float(row["radius_m"]),
                blocking=bool(row["blocking"]),
                age_days=age_days,
                lat=lat,
                lon=lon,
                source=row["source"],
                active=True,
            )
            incidents.append(inc)

        return incidents

    def clear_all(self) -> None:
        """Clear all records (used for test teardown)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM incidents")
            conn.commit()
