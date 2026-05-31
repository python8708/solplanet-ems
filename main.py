"""Script principal del EMS Solplanet standalone.

Este main:
- Valida configuración
- Inicializa logging, Solplanet, MySQL y MQTT
- Descubre dispositivos al arrancar
- Publica estado completo por MQTT
- Guarda estado en base de datos
- Procesa comandos MQTT
- Maneja cierre limpio
"""

from __future__ import annotations

import signal
import sys
import time
from typing import Optional

from commands import CommandHandler
from config import config
from database import Database
from energy_stats import EnergyStats
from logger import configure_logging, setup_logger
from mqtt_client import MQTTClient
from solplanet_client import SolplanetClient, SolplanetClientError

configure_logging(config.LOG_LEVEL)
logger = setup_logger(__name__)


# ============================================================
# VARIABLES GLOBALES
# ============================================================

solplanet: Optional[SolplanetClient] = None
database: Optional[Database] = None
mqtt: Optional[MQTTClient] = None
command_handler: Optional[CommandHandler] = None
energy_stats: Optional[EnergyStats] = None

running = True
cycle_count = 0


# ============================================================
# HELPERS
# ============================================================

def _should_force_refresh(cycle: int) -> bool:
    """
    Forzar refresh en cada ciclo para evitar datos cacheados del meter.
    El dongle Solplanet soporta consultas cada 10s sin problema.
    """
    return True


def _safe_publish_availability(online: bool) -> None:
    try:
        if mqtt:
            mqtt.publish_availability(online)
    except Exception as e:
        logger.debug("No se pudo publicar availability=%s: %s", online, e)


# ============================================================
# MANEJO DE SEÑALES
# ============================================================

def _shutdown(exit_code: int = 0) -> None:
    """Cierre ordenado del sistema."""
    global running
    running = False

    logger.info("Cerrando EMS Solplanet...")

    _safe_publish_availability(False)

    try:
        if mqtt:
            mqtt.disconnect()
    except Exception as e:
        logger.debug("Error cerrando MQTT: %s", e)

    try:
        if solplanet:
            solplanet.close()
    except Exception as e:
        logger.debug("Error cerrando cliente Solplanet: %s", e)

    logger.info("Sistema detenido")
    sys.exit(exit_code)


def signal_handler(sig, frame):
    """Captura señales del sistema."""
    logger.info("Señal de terminación recibida: %s", sig)
    _shutdown(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# CALLBACK DE COMANDOS MQTT
# ============================================================

def on_command_received(payload: dict):
    """Procesa un comando recibido por MQTT."""
    global command_handler

    if not command_handler:
        logger.warning("CommandHandler no inicializado")
        return

    logger.info("Procesando comando MQTT entrante")
    ok = command_handler.process_command(payload)

    if ok:
        logger.info("✅ Comando procesado correctamente")

        # Tras una escritura, limpiamos caches del cliente para
        # que el siguiente ciclo lea el estado actualizado.
        try:
            if solplanet:
                solplanet.refresh(settle_seconds=1.5)
        except Exception as e:
            logger.debug("No se pudo refrescar tras comando MQTT: %s", e)
    else:
        logger.warning("⚠️ El comando no se pudo aplicar")


# ============================================================
# INICIALIZACIÓN
# ============================================================

def initialize_solplanet() -> SolplanetClient:
    """Inicializa cliente Solplanet y realiza discovery."""
    logger.info("Inicializando cliente Solplanet...")
    client = SolplanetClient(
        base_url=config.INVERTER_URL,
        battery_sn=config.BATTERY_SN,
        timeout=config.HTTP_TIMEOUT,
        retries=config.HTTP_RETRIES,
        retry_delay=config.HTTP_RETRY_DELAY,
    )

    discovery = client.get_discovery(force=True)
    logger.info(
        "Discovery OK | inverter_sn=%s | has_meter=%s | has_battery=%s",
        discovery.inverter_sn,
        discovery.has_meter,
        discovery.has_battery,
    )

    if discovery.dongle:
        logger.info(
            "Dongle detectado | psn=%s | modelo=%s | sw=%s",
            discovery.dongle.psn,
            discovery.dongle.mod,
            discovery.dongle.sw,
        )

    if discovery.inverter:
        logger.info(
            "Inversor detectado | isn=%s | rate=%sW | safety=%s",
            discovery.inverter.isn,
            discovery.inverter.rate,
            discovery.inverter.safety,
        )

    if discovery.meter:
        logger.info(
            "Meter detectado | sn=%s | modelo=%s | pac=%s",
            discovery.meter.sn,
            discovery.meter.name,
            discovery.meter.meter_pac,
        )

    if discovery.battery:
        logger.info(
            "Batería detectada | sn=%s | modo=%s | charge_max=%s | discharge_max=%s",
            discovery.battery.sn or discovery.battery.isn,
            discovery.battery.mode_name,
            discovery.battery.charge_max,
            discovery.battery.discharge_max,
        )

    return client


def initialize_database() -> Optional[Database]:
    """Inicializa la base de datos si está habilitada."""
    if not config.DB_ENABLED:
        logger.info("Base de datos deshabilitada por configuración")
        return None

    logger.info("Inicializando base de datos...")
    db = Database(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )

    if not db.test_connection():
        raise RuntimeError("No se pudo conectar a MySQL")

    if not db.initialize_tables():
        raise RuntimeError("No se pudieron inicializar las tablas MySQL")

    logger.info("Base de datos inicializada correctamente")
    return db


def initialize_mqtt() -> Optional[MQTTClient]:
    """Inicializa MQTT si está habilitado."""
    if not config.MQTT_ENABLED:
        logger.info("MQTT deshabilitado por configuración")
        return None

    logger.info("Inicializando MQTT...")
    mqtt_client = MQTTClient(
        host=config.MQTT_HOST,
        port=config.MQTT_PORT,
        username=config.MQTT_USER,
        password=config.MQTT_PASSWORD,
        client_id=config.MQTT_CLIENT_ID,
        keepalive=config.MQTT_KEEPALIVE,
        qos=config.MQTT_QOS,
        availability_topic=config.MQTT_TOPIC_AVAILABILITY,
    )

    mqtt_client.set_command_callback(on_command_received)

    if not mqtt_client.connect():
        logger.warning("MQTT connect() no confirmó conexión inmediata")

    mqtt_client.wait_until_connected(timeout=10.0)

    mqtt_client.subscribe(config.MQTT_TOPIC_CMD)

    logger.info(
        "MQTT listo | state_topic=%s | cmd_topic=%s | availability=%s",
        config.effective_mqtt_state_topic,
        config.MQTT_TOPIC_CMD,
        config.MQTT_TOPIC_AVAILABILITY,
    )
    return mqtt_client


def initialize() -> bool:
    """Inicializa todos los componentes del sistema."""
    global solplanet, database, mqtt, command_handler, energy_stats

    try:
        logger.info("Validando configuración...")
        config.validate()
        logger.info("Configuración validada")

        logger.debug("Configuración efectiva: %s", config.to_dict())

        solplanet = initialize_solplanet()
        database = initialize_database()
        mqtt = initialize_mqtt()

        if database:
            energy_stats = EnergyStats(database)
            energy_stats.initialize_table()
            logger.info("Energy stats inicializado")

        logger.info("Inicializando manejador de comandos...")
        command_handler = CommandHandler(solplanet)

        _safe_publish_availability(True)

        logger.info("Inicialización completa")
        return True

    except Exception as e:
        logger.exception("❌ Error en inicialización: %s", e)
        return False


# ============================================================
# OPERACIONES DE CICLO
# ============================================================

def publish_state(force_refresh: bool = False) -> bool:
    """Lee estado completo y lo publica por MQTT."""
    if not solplanet:
        logger.error("Cliente Solplanet no inicializado")
        return False

    state = solplanet.get_state(force_refresh=force_refresh)
    payload = state.to_dict()

    logger.info(
        "Estado | Solar=%sW | Consumo=%.0fW | Grid=%sW | Battery=%sW | SOC=%s%% | Mode=%s",
        state.solar,
        state.consumo,
        state.grid,
        state.battery_power,
        state.soc,
        state.mode_name or state.mode,
    )

    if mqtt:
        mqtt_ok = mqtt.publish(
            config.effective_mqtt_state_topic,
            payload,
            retain=True,
            skip_if_unchanged=False,
        )
        if not mqtt_ok:
            logger.warning("⚠️ No se pudo publicar estado en MQTT")

        if getattr(config, "PUBLISH_DEBUG_EVERY_CYCLE", False):
            try:
                debug_bundle = solplanet.export_debug_bundle(force_refresh=False)
                mqtt.publish(
                    config.MQTT_TOPIC_DEBUG,
                    debug_bundle,
                    retain=False,
                    skip_if_unchanged=False,
                )
            except Exception as e:
                logger.warning("⚠️ No se pudo publicar debug bundle: %s", e)

    if database:
        try:
            db_ok = database.save_system_state(
                state,
                save_history=config.DB_SAVE_HISTORY,
            )
            if not db_ok:
                logger.warning("⚠️ No se pudo guardar estado en MySQL")
        except Exception as e:
            logger.warning("⚠️ Error guardando estado en MySQL: %s", e)

    if energy_stats and mqtt:
        try:
            stats = energy_stats.update(state)
            if stats:
                mqtt.publish(
                    config.MQTT_TOPIC_ENERGY_STATS,
                    stats,
                    retain=True,
                    skip_if_unchanged=True,
                )
        except Exception as e:
            logger.warning("⚠️ Error publicando energy stats: %s", e)

    return True


def main_loop():
    """Loop principal del EMS."""
    global running, cycle_count

    logger.info("EMS Solplanet activo")
    logger.info("Intervalo de sondeo: %ss", config.POLL_INTERVAL)

    while running:
        started_at = time.time()
        cycle_count += 1
        force_refresh = _should_force_refresh(cycle_count)

        try:
            logger.debug(
                "Iniciando ciclo #%s | force_refresh=%s",
                cycle_count,
                force_refresh,
            )
            publish_state(force_refresh=force_refresh)
            _safe_publish_availability(True)

        except SolplanetClientError as e:
            logger.error("❌ Error Solplanet en ciclo #%s: %s", cycle_count, e)
            _safe_publish_availability(False)

        except Exception as e:
            logger.exception("❌ Error inesperado en ciclo #%s: %s", cycle_count, e)
            _safe_publish_availability(False)

        elapsed = time.time() - started_at
        sleep_for = max(0.0, float(config.POLL_INTERVAL) - elapsed)

        logger.debug(
            "Ciclo #%s completado en %.2fs | sleep=%.2fs",
            cycle_count,
            elapsed,
            sleep_for,
        )

        if sleep_for > 0:
            time.sleep(sleep_for)


# ============================================================
# ENTRYPOINT
# ============================================================

def main() -> int:
    """Punto de entrada principal."""
    if not initialize():
        return 1

    try:
        main_loop()
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupción manual recibida")
        return 0
    finally:
        _safe_publish_availability(False)

        try:
            if mqtt:
                mqtt.disconnect()
        except Exception:
            pass

        try:
            if solplanet:
                solplanet.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
