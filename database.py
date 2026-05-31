"""Gestión de base de datos MySQL para el EMS Solplanet."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

import mysql.connector
from mysql.connector.connection import MySQLConnection

from logger import setup_logger
from models import SystemState

logger = setup_logger(__name__)


class Database:
    """Gestor de base de datos MySQL."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        database: str,
        port: int = 3306,
    ):
        """
        Args:
            host: Host MySQL
            user: Usuario MySQL
            password: Contraseña MySQL
            database: Nombre de la base de datos
            port: Puerto MySQL
        """
        self.config = {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "database": database,
            "autocommit": False,
            "use_pure": True,
        }

    # ============================================================
    # CONEXIÓN
    # ============================================================

    @contextmanager
    def get_connection(self) -> Generator[MySQLConnection, None, None]:
        """Context manager para conexión MySQL."""
        conn: Optional[MySQLConnection] = None
        try:
            conn = mysql.connector.connect(**self.config)
            yield conn
            conn.commit()
        except mysql.connector.Error as e:
            logger.error("Error MySQL: %s", e)
            if conn:
                conn.rollback()
            raise
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()

    def test_connection(self) -> bool:
        """Comprueba conexión a MySQL."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
            logger.info("Conexión MySQL OK")
            return True
        except Exception as e:
            logger.error("Error probando conexión MySQL: %s", e)
            return False

    # ============================================================
    # INICIALIZACIÓN DE TABLAS
    # ============================================================

    def initialize_table(self) -> bool:
        """Compatibilidad con tu proyecto anterior."""
        return self.initialize_tables()

    def initialize_tables(self) -> bool:
        """Crea tablas necesarias e inserta fila inicial de energy_live."""
        create_energy_live = """
        CREATE TABLE IF NOT EXISTS energy_live (
            id TINYINT PRIMARY KEY,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,

            timestamp_str VARCHAR(32) NULL,

            solar INT NOT NULL DEFAULT 0,
            solar_today DECIMAL(12,2) NOT NULL DEFAULT 0,
            solar_total DECIMAL(12,2) NOT NULL DEFAULT 0,
            pv1_power INT NULL,
            pv2_power INT NULL,
            pv1_voltage DECIMAL(10,1) NULL,
            pv2_voltage DECIMAL(10,1) NULL,
            pv1_current DECIMAL(10,1) NULL,
            pv2_current DECIMAL(10,1) NULL,

            grid INT NOT NULL DEFAULT 0,
            import_grid INT NOT NULL DEFAULT 0,
            export_grid INT NOT NULL DEFAULT 0,
            import_today DECIMAL(12,2) NOT NULL DEFAULT 0,
            export_today DECIMAL(12,2) NOT NULL DEFAULT 0,
            import_total DECIMAL(12,2) NOT NULL DEFAULT 0,
            export_total DECIMAL(12,2) NOT NULL DEFAULT 0,

            soc INT NOT NULL DEFAULT 0,
            soh INT NOT NULL DEFAULT 0,
            battery_power INT NOT NULL DEFAULT 0,
            battery_charge INT NOT NULL DEFAULT 0,
            battery_discharge INT NOT NULL DEFAULT 0,
            battery_voltage DECIMAL(10,1) NOT NULL DEFAULT 0,
            battery_current DECIMAL(10,1) NOT NULL DEFAULT 0,
            battery_temp DECIMAL(10,1) NOT NULL DEFAULT 0,
            battery_state INT NOT NULL DEFAULT 0,
            battery_state_name VARCHAR(64) NULL,
            battery_comm_status INT NOT NULL DEFAULT 0,
            battery_comm_status_name VARCHAR(64) NULL,
            battery_energy_in DECIMAL(12,2) NOT NULL DEFAULT 0,
            battery_energy_out DECIMAL(12,2) NOT NULL DEFAULT 0,
            battery_charge_total DECIMAL(12,2) NOT NULL DEFAULT 0,

            consumo DECIMAL(12,2) NOT NULL DEFAULT 0,
            autosuf DECIMAL(6,2) NOT NULL DEFAULT 0,
            autoconsumo DECIMAL(6,2) NOT NULL DEFAULT 0,

            mode INT NOT NULL DEFAULT 0,
            mode_name VARCHAR(64) NULL,
            charge_max INT NOT NULL DEFAULT 100,
            discharge_max INT NOT NULL DEFAULT 10,

            inverter_status INT NOT NULL DEFAULT 0,
            inverter_status_name VARCHAR(64) NULL,
            inverter_error INT NOT NULL DEFAULT 0,
            inverter_error_name VARCHAR(128) NULL,
            inverter_warning INT NOT NULL DEFAULT 0,
            inverter_rate INT NOT NULL DEFAULT 0,
            inverter_safety INT NOT NULL DEFAULT 0,
            inverter_temp DECIMAL(10,1) NOT NULL DEFAULT 0,
            inverter_frequency DECIMAL(10,2) NOT NULL DEFAULT 0,
            inverter_pf DECIMAL(10,2) NOT NULL DEFAULT 0,
            inverter_ac_voltage DECIMAL(10,1) NOT NULL DEFAULT 0,
            inverter_ac_current DECIMAL(10,1) NOT NULL DEFAULT 0,
            inverter_hours_total INT NOT NULL DEFAULT 0,

            schedule_pin INT NOT NULL DEFAULT 0,
            schedule_pout INT NOT NULL DEFAULT 0,

            has_meter BOOLEAN NOT NULL DEFAULT FALSE,
            has_battery BOOLEAN NOT NULL DEFAULT FALSE,
            inverter_sn VARCHAR(64) NULL,
            battery_sn VARCHAR(64) NULL
        )
        """

        create_energy_history = """
        CREATE TABLE IF NOT EXISTS energy_history (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            timestamp_str VARCHAR(32) NULL,

            solar INT NOT NULL DEFAULT 0,
            solar_today DECIMAL(12,2) NOT NULL DEFAULT 0,
            solar_total DECIMAL(12,2) NOT NULL DEFAULT 0,
            pv1_power INT NULL,
            pv2_power INT NULL,
            pv1_voltage DECIMAL(10,1) NULL,
            pv2_voltage DECIMAL(10,1) NULL,
            pv1_current DECIMAL(10,1) NULL,
            pv2_current DECIMAL(10,1) NULL,

            grid INT NOT NULL DEFAULT 0,
            import_grid INT NOT NULL DEFAULT 0,
            export_grid INT NOT NULL DEFAULT 0,
            import_today DECIMAL(12,2) NOT NULL DEFAULT 0,
            export_today DECIMAL(12,2) NOT NULL DEFAULT 0,
            import_total DECIMAL(12,2) NOT NULL DEFAULT 0,
            export_total DECIMAL(12,2) NOT NULL DEFAULT 0,

            soc INT NOT NULL DEFAULT 0,
            soh INT NOT NULL DEFAULT 0,
            battery_power INT NOT NULL DEFAULT 0,
            battery_charge INT NOT NULL DEFAULT 0,
            battery_discharge INT NOT NULL DEFAULT 0,
            battery_voltage DECIMAL(10,1) NOT NULL DEFAULT 0,
            battery_current DECIMAL(10,1) NOT NULL DEFAULT 0,
            battery_temp DECIMAL(10,1) NOT NULL DEFAULT 0,
            battery_state INT NOT NULL DEFAULT 0,
            battery_state_name VARCHAR(64) NULL,
            battery_comm_status INT NOT NULL DEFAULT 0,
            battery_comm_status_name VARCHAR(64) NULL,
            battery_energy_in DECIMAL(12,2) NOT NULL DEFAULT 0,
            battery_energy_out DECIMAL(12,2) NOT NULL DEFAULT 0,
            battery_charge_total DECIMAL(12,2) NOT NULL DEFAULT 0,

            consumo DECIMAL(12,2) NOT NULL DEFAULT 0,
            autosuf DECIMAL(6,2) NOT NULL DEFAULT 0,
            autoconsumo DECIMAL(6,2) NOT NULL DEFAULT 0,

            mode INT NOT NULL DEFAULT 0,
            mode_name VARCHAR(64) NULL,
            charge_max INT NOT NULL DEFAULT 100,
            discharge_max INT NOT NULL DEFAULT 10,

            inverter_status INT NOT NULL DEFAULT 0,
            inverter_status_name VARCHAR(64) NULL,
            inverter_error INT NOT NULL DEFAULT 0,
            inverter_error_name VARCHAR(128) NULL,
            inverter_warning INT NOT NULL DEFAULT 0,
            inverter_rate INT NOT NULL DEFAULT 0,
            inverter_safety INT NOT NULL DEFAULT 0,
            inverter_temp DECIMAL(10,1) NOT NULL DEFAULT 0,
            inverter_frequency DECIMAL(10,2) NOT NULL DEFAULT 0,
            inverter_pf DECIMAL(10,2) NOT NULL DEFAULT 0,
            inverter_ac_voltage DECIMAL(10,1) NOT NULL DEFAULT 0,
            inverter_ac_current DECIMAL(10,1) NOT NULL DEFAULT 0,
            inverter_hours_total INT NOT NULL DEFAULT 0,

            schedule_pin INT NOT NULL DEFAULT 0,
            schedule_pout INT NOT NULL DEFAULT 0,

            has_meter BOOLEAN NOT NULL DEFAULT FALSE,
            has_battery BOOLEAN NOT NULL DEFAULT FALSE,
            inverter_sn VARCHAR(64) NULL,
            battery_sn VARCHAR(64) NULL,

            INDEX idx_created_at (created_at),
            INDEX idx_timestamp_str (timestamp_str),
            INDEX idx_inverter_sn (inverter_sn),
            INDEX idx_battery_sn (battery_sn)
        )
        """

        insert_energy_live_row = """
        INSERT IGNORE INTO energy_live (id) VALUES (1)
        """

        create_energy_daily = """
        CREATE TABLE IF NOT EXISTS energy_daily (
            day DATE PRIMARY KEY,
            import_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
            export_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
            solar_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
            consumo_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(create_energy_live)
                cursor.execute(create_energy_history)
                cursor.execute(create_energy_daily)
                cursor.execute(insert_energy_live_row)
                cursor.close()

            logger.info("Tablas MySQL inicializadas correctamente")
            return True

        except Exception as e:
            logger.error("Error inicializando tablas MySQL: %s", e)
            return False

    # ============================================================
    # HELPERS DE SERIALIZACIÓN
    # ============================================================

    def _state_tuple(self, state: SystemState) -> tuple:
        """Serializa SystemState en el orden exacto de columnas."""
        return (
            state.timestamp,

            state.solar,
            state.solar_today,
            state.solar_total,
            state.pv1_power,
            state.pv2_power,
            state.pv1_voltage,
            state.pv2_voltage,
            state.pv1_current,
            state.pv2_current,

            state.grid,
            state.import_grid,
            state.export_grid,
            state.import_today,
            state.export_today,
            state.import_total,
            state.export_total,

            state.soc,
            state.soh,
            state.battery_power,
            state.battery_charge,
            state.battery_discharge,
            state.battery_voltage,
            state.battery_current,
            state.battery_temp,
            state.battery_state,
            state.battery_state_name,
            state.battery_comm_status,
            state.battery_comm_status_name,
            state.battery_energy_in,
            state.battery_energy_out,
            state.battery_charge_total,

            state.consumo,
            state.autosuf,
            state.autoconsumo,

            state.mode,
            state.mode_name,
            state.charge_max,
            state.discharge_max,

            state.inverter_status,
            state.inverter_status_name,
            state.inverter_error,
            state.inverter_error_name,
            state.inverter_warning,
            state.inverter_rate,
            state.inverter_safety,
            state.inverter_temp,
            state.inverter_frequency,
            state.inverter_pf,
            state.inverter_ac_voltage,
            state.inverter_ac_current,
            state.inverter_hours_total,

            state.schedule_pin,
            state.schedule_pout,

            int(state.has_meter),
            int(state.has_battery),
            state.inverter_sn,
            state.battery_sn,
        )

    # ============================================================
    # GUARDADO LIVE
    # ============================================================

    def save_energy_live(self, state: SystemState) -> bool:
        """Guarda el último estado en energy_live."""
        query = """
        UPDATE energy_live SET
            updated_at = NOW(),
            timestamp_str = %s,

            solar = %s,
            solar_today = %s,
            solar_total = %s,
            pv1_power = %s,
            pv2_power = %s,
            pv1_voltage = %s,
            pv2_voltage = %s,
            pv1_current = %s,
            pv2_current = %s,

            grid = %s,
            import_grid = %s,
            export_grid = %s,
            import_today = %s,
            export_today = %s,
            import_total = %s,
            export_total = %s,

            soc = %s,
            soh = %s,
            battery_power = %s,
            battery_charge = %s,
            battery_discharge = %s,
            battery_voltage = %s,
            battery_current = %s,
            battery_temp = %s,
            battery_state = %s,
            battery_state_name = %s,
            battery_comm_status = %s,
            battery_comm_status_name = %s,
            battery_energy_in = %s,
            battery_energy_out = %s,
            battery_charge_total = %s,

            consumo = %s,
            autosuf = %s,
            autoconsumo = %s,

            mode = %s,
            mode_name = %s,
            charge_max = %s,
            discharge_max = %s,

            inverter_status = %s,
            inverter_status_name = %s,
            inverter_error = %s,
            inverter_error_name = %s,
            inverter_warning = %s,
            inverter_rate = %s,
            inverter_safety = %s,
            inverter_temp = %s,
            inverter_frequency = %s,
            inverter_pf = %s,
            inverter_ac_voltage = %s,
            inverter_ac_current = %s,
            inverter_hours_total = %s,

            schedule_pin = %s,
            schedule_pout = %s,

            has_meter = %s,
            has_battery = %s,
            inverter_sn = %s,
            battery_sn = %s
        WHERE id = 1
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, self._state_tuple(state))
                cursor.close()

            return True

        except Exception as e:
            logger.error("Error guardando energy_live: %s", e)
            return False

    # ============================================================
    # GUARDADO HISTÓRICO
    # ============================================================

    def save_energy_history(self, state: SystemState) -> bool:
        """Inserta una fila histórica en energy_history."""
        query = """
        INSERT INTO energy_history (
            timestamp_str,

            solar,
            solar_today,
            solar_total,
            pv1_power,
            pv2_power,
            pv1_voltage,
            pv2_voltage,
            pv1_current,
            pv2_current,

            grid,
            import_grid,
            export_grid,
            import_today,
            export_today,
            import_total,
            export_total,

            soc,
            soh,
            battery_power,
            battery_charge,
            battery_discharge,
            battery_voltage,
            battery_current,
            battery_temp,
            battery_state,
            battery_state_name,
            battery_comm_status,
            battery_comm_status_name,
            battery_energy_in,
            battery_energy_out,
            battery_charge_total,

            consumo,
            autosuf,
            autoconsumo,

            mode,
            mode_name,
            charge_max,
            discharge_max,

            inverter_status,
            inverter_status_name,
            inverter_error,
            inverter_error_name,
            inverter_warning,
            inverter_rate,
            inverter_safety,
            inverter_temp,
            inverter_frequency,
            inverter_pf,
            inverter_ac_voltage,
            inverter_ac_current,
            inverter_hours_total,

            schedule_pin,
            schedule_pout,

            has_meter,
            has_battery,
            inverter_sn,
            battery_sn
        ) VALUES (
            %s,

            %s, %s, %s, %s, %s, %s, %s, %s, %s,

            %s, %s, %s, %s, %s, %s, %s,

            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,

            %s, %s, %s,

            %s, %s, %s, %s,

            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,

            %s, %s,

            %s, %s, %s, %s
        )
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, self._state_tuple(state))
                cursor.close()

            return True

        except Exception as e:
            logger.error("Error guardando energy_history: %s", e)
            return False

    def cleanup_history(self, limit: int = 5) -> bool:
        """Mantiene solo los últimos N registros en energy_history."""
        try:
            limit = int(limit)
            if limit <= 0:
                logger.warning("cleanup_history recibió un límite inválido: %s", limit)
                return False

            query = f"""
            DELETE FROM energy_history
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id
                    FROM energy_history
                    ORDER BY id DESC
                    LIMIT {limit}
                ) AS t
            )
            """

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                cursor.close()

            return True

        except Exception as e:
            logger.error("Error limpiando energy_history: %s", e)
            return False

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def save_system_state(
        self,
        state: SystemState,
        save_history: bool = True,
        history_limit: int = 5,
    ) -> bool:
        """Guarda el estado completo.

        - siempre actualiza energy_live
        - opcionalmente inserta en energy_history
        - limita el histórico para que no crezca infinito
        """
        try:
            live_ok = self.save_energy_live(state)
            if not live_ok:
                return False

            if save_history:
                history_ok = self.save_energy_history(state)
                if not history_ok:
                    return False

                cleanup_ok = self.cleanup_history(limit=history_limit)
                if not cleanup_ok:
                    logger.warning(
                        "No se pudo limpiar energy_history, pero el guardado sí se realizó"
                    )

            return True

        except Exception as e:
            logger.error("Error guardando estado del sistema: %s", e)
            return False

    # ============================================================
    # CONSULTAS RÁPIDAS
    # ============================================================

    def get_last_live_timestamp(self) -> Optional[str]:
        """Devuelve timestamp_str del último estado live."""
        query = "SELECT timestamp_str FROM energy_live WHERE id = 1"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                row = cursor.fetchone()
                cursor.close()

            if not row:
                return None
            return row[0]

        except Exception as e:
            logger.error("Error leyendo último timestamp live: %s", e)
            return None


__all__ = ["Database"]
