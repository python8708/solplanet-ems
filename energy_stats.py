"""Estadísticas de energía: día, semana, mes, total.

Guarda un snapshot diario al detectar cambio de día y calcula
acumulados semanales/mensuales a partir de la tabla energy_daily.
Auto-limpia registros de más de 62 días.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional

from logger import setup_logger

logger = setup_logger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS energy_daily (
    day DATE PRIMARY KEY,
    import_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    export_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    solar_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    consumo_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CLEANUP_DAYS = 62


class EnergyStats:
    """Calcula y publica estadísticas de energía."""

    def __init__(self, database):
        self.db = database
        self._last_day: Optional[date] = None

    def initialize_table(self) -> bool:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(CREATE_TABLE_SQL)
                cursor.close()
            return True
        except Exception as e:
            logger.error("Error creando energy_daily: %s", e)
            return False

    def update(self, state) -> Optional[Dict]:
        """Llamar cada ciclo. Guarda snapshot si cambió el día y devuelve stats."""
        today = date.today()

        # Guardar snapshot del día actual (upsert con los valores _today)
        self._save_snapshot(today, state)

        # Detectar cambio de día para cleanup
        if self._last_day and self._last_day != today:
            self._cleanup()
        self._last_day = today

        return self._calculate_stats(today, state)

    def _save_snapshot(self, day: date, state) -> None:
        """Upsert del día actual con los valores _today del inversor."""
        query = """
        INSERT INTO energy_daily (day, import_kwh, export_kwh, solar_kwh, consumo_kwh)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            import_kwh = VALUES(import_kwh),
            export_kwh = VALUES(export_kwh),
            solar_kwh = VALUES(solar_kwh),
            consumo_kwh = VALUES(consumo_kwh)
        """
        try:
            # consumo_today lo estimamos como solar_today + import_today - export_today
            consumo_today = max(0.0, state.solar_today + state.import_today - state.export_today)
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    day,
                    round(state.import_today, 2),
                    round(state.export_today, 2),
                    round(state.solar_today, 2),
                    round(consumo_today, 2),
                ))
                cursor.close()
        except Exception as e:
            logger.error("Error guardando snapshot diario: %s", e)

    def _calculate_stats(self, today: date, state) -> Dict:
        """Calcula hoy/semana/mes/total."""
        consumo_today = max(0.0, state.solar_today + state.import_today - state.export_today)

        # Semana: lunes a hoy
        monday = today - timedelta(days=today.weekday())
        week = self._sum_range(monday, today)

        # Mes: día 1 a hoy
        first_of_month = today.replace(day=1)
        month = self._sum_range(first_of_month, today)

        return {
            "import_today": round(state.import_today, 2),
            "export_today": round(state.export_today, 2),
            "solar_today": round(state.solar_today, 2),
            "consumo_today": round(consumo_today, 2),
            "import_week": round(week.get("import_kwh", 0), 2),
            "export_week": round(week.get("export_kwh", 0), 2),
            "solar_week": round(week.get("solar_kwh", 0), 2),
            "consumo_week": round(week.get("consumo_kwh", 0), 2),
            "import_month": round(month.get("import_kwh", 0), 2),
            "export_month": round(month.get("export_kwh", 0), 2),
            "solar_month": round(month.get("solar_kwh", 0), 2),
            "consumo_month": round(month.get("consumo_kwh", 0), 2),
            "import_total": round(state.import_total, 1),
            "export_total": round(state.export_total, 1),
            "solar_total": round(state.solar_total, 1),
        }

    def _sum_range(self, start: date, end: date) -> Dict[str, float]:
        """Suma los valores de energy_daily entre start y end (inclusive)."""
        query = """
        SELECT
            COALESCE(SUM(import_kwh), 0),
            COALESCE(SUM(export_kwh), 0),
            COALESCE(SUM(solar_kwh), 0),
            COALESCE(SUM(consumo_kwh), 0)
        FROM energy_daily
        WHERE day BETWEEN %s AND %s
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (start, end))
                row = cursor.fetchone()
                cursor.close()
            if row:
                return {
                    "import_kwh": float(row[0]),
                    "export_kwh": float(row[1]),
                    "solar_kwh": float(row[2]),
                    "consumo_kwh": float(row[3]),
                }
        except Exception as e:
            logger.error("Error calculando rango %s-%s: %s", start, end, e)
        return {}

    def _cleanup(self) -> None:
        """Borra registros de más de 62 días."""
        cutoff = date.today() - timedelta(days=CLEANUP_DAYS)
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM energy_daily WHERE day < %s", (cutoff,))
                cursor.close()
            logger.info("Limpieza energy_daily: eliminados registros anteriores a %s", cutoff)
        except Exception as e:
            logger.error("Error limpiando energy_daily: %s", e)
