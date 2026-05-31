#cat > config.py << 'EOF'
"""Configuración central del sistema EMS Solplanet.

Objetivos:
- Mantener compatibilidad con tu proyecto actual
- Añadir validación limpia y flexible
- Permitir descubrimiento automático de batería
- Preparar topics y ajustes nuevos sin romper HA
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    """Lee booleanos desde variables de entorno."""
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _get_int(name: str, default: int) -> int:
    """Lee enteros con fallback seguro."""
    value = os.getenv(name)
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


@dataclass(slots=True)
class Config:
    """Configuración validada del sistema."""

    # ============================================================
    # SOLPLANET / INVERSOR
    # ============================================================

    INVERTER_URL: str = os.getenv("INVERTER_URL", "").strip()
    BATTERY_SN: Optional[str] = (os.getenv("BATTERY_SN") or "").strip() or None
    HTTP_TIMEOUT: int = _get_int("HTTP_TIMEOUT", 8)
    HTTP_RETRIES: int = _get_int("HTTP_RETRIES", 3)
    HTTP_RETRY_DELAY: int = _get_int("HTTP_RETRY_DELAY", 1)

    # ============================================================
    # BASE DE DATOS
    # ============================================================

    DB_ENABLED: bool = _get_bool("DB_ENABLED", True)
    DB_HOST: str = os.getenv("DB_HOST", "localhost").strip()
    DB_PORT: int = _get_int("DB_PORT", 3306)
    DB_USER: str = os.getenv("DB_USER", "").strip()
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "").strip()
    DB_NAME: str = os.getenv("DB_NAME", "solplanet_ems").strip()
    DB_SAVE_HISTORY: bool = _get_bool("DB_SAVE_HISTORY", True)

    # ============================================================
    # MQTT
    # ============================================================

    MQTT_ENABLED: bool = _get_bool("MQTT_ENABLED", True)
    MQTT_HOST: str = os.getenv("MQTT_HOST", "localhost").strip()
    MQTT_PORT: int = _get_int("MQTT_PORT", 1883)
    MQTT_USER: Optional[str] = (os.getenv("MQTT_USER") or "").strip() or None
    MQTT_PASSWORD: Optional[str] = (os.getenv("MQTT_PASSWORD") or "").strip() or None
    MQTT_CLIENT_ID: Optional[str] = (os.getenv("MQTT_CLIENT_ID") or "").strip() or None
    MQTT_KEEPALIVE: int = _get_int("MQTT_KEEPALIVE", 60)
    MQTT_QOS: int = _get_int("MQTT_QOS", 1)

    # Topics compatibles + extendidos
    MQTT_TOPIC_STATE: str = os.getenv("MQTT_TOPIC_STATE", "solplanet/estado").strip()
    MQTT_TOPIC_CMD: str = os.getenv("MQTT_TOPIC_CMD", "solplanet/comando").strip()
    MQTT_TOPIC_DEBUG: str = os.getenv("MQTT_TOPIC_DEBUG", "solplanet/debug").strip()
    MQTT_TOPIC_AVAILABILITY: str = os.getenv(
        "MQTT_TOPIC_AVAILABILITY",
        "solplanet/disponibilidad",
    ).strip()
    MQTT_TOPIC_ENERGY_STATS: str = os.getenv(
        "MQTT_TOPIC_ENERGY_STATS",
        "solplanet/energia",
    ).strip()

    # Compatibilidad con config antigua que usaba MQTT_TOPIC único
    MQTT_TOPIC: str = os.getenv("MQTT_TOPIC", "").strip()

    # ============================================================
    # SISTEMA
    # ============================================================

    POLL_INTERVAL: int = _get_int("POLL_INTERVAL", 10)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    SAVE_INTERVAL: int = _get_int("SAVE_INTERVAL", 5)
    PUBLISH_DEBUG_EVERY_CYCLE: bool = _get_bool("PUBLISH_DEBUG_EVERY_CYCLE", False)

    # ============================================================
    # HELPERS
    # ============================================================

    @property
    def effective_mqtt_state_topic(self) -> str:
        """Topic final de estado.

        Compatibilidad:
        - si existe MQTT_TOPIC_STATE, manda
        - si no, usa MQTT_TOPIC
        """
        if self.MQTT_TOPIC_STATE:
            return self.MQTT_TOPIC_STATE
        if self.MQTT_TOPIC:
            return self.MQTT_TOPIC
        return "solplanet/estado"

    @property
    def db_configured(self) -> bool:
        """Indica si DB tiene mínimos para conectarse."""
        return all([
            self.DB_HOST,
            self.DB_PORT,
            self.DB_USER,
            self.DB_PASSWORD,
            self.DB_NAME,
        ])

    @property
    def mqtt_configured(self) -> bool:
        """Indica si MQTT tiene mínimos para conectarse."""
        return bool(self.MQTT_HOST and self.MQTT_PORT)

    def validate(self) -> None:
        """Valida la configuración crítica."""
        missing = []

        if not self.INVERTER_URL:
            missing.append("INVERTER_URL")

        if missing:
            raise ValueError(
                "❌ Faltan variables de entorno requeridas: "
                + ", ".join(missing)
                + ". Copia .env.example a .env y configúralo correctamente."
            )

        if self.DB_ENABLED and not self.db_configured:
            raise ValueError(
                "❌ DB_ENABLED=true pero faltan variables de base de datos "
                "(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)."
            )

        if self.MQTT_ENABLED and not self.mqtt_configured:
            raise ValueError(
                "❌ MQTT_ENABLED=true pero faltan variables MQTT mínimas "
                "(MQTT_HOST y MQTT_PORT)."
            )

        if self.POLL_INTERVAL <= 0:
            raise ValueError("❌ POLL_INTERVAL debe ser mayor que 0")

        if self.SAVE_INTERVAL <= 0:
            raise ValueError("❌ SAVE_INTERVAL debe ser mayor que 0")

        if self.HTTP_TIMEOUT <= 0:
            raise ValueError("❌ HTTP_TIMEOUT debe ser mayor que 0")

        if self.HTTP_RETRIES <= 0:
            raise ValueError("❌ HTTP_RETRIES debe ser mayor que 0")

        if self.MQTT_QOS not in (0, 1, 2):
            raise ValueError("❌ MQTT_QOS debe ser 0, 1 o 2")

    def to_dict(self) -> dict:
        """Devuelve configuración serializable ocultando secretos."""
        data = asdict(self)

        if data.get("DB_PASSWORD"):
            data["DB_PASSWORD"] = "***"
        if data.get("MQTT_PASSWORD"):
            data["MQTT_PASSWORD"] = "***"

        data["effective_mqtt_state_topic"] = self.effective_mqtt_state_topic
        data["db_configured"] = self.db_configured
        data["mqtt_configured"] = self.mqtt_configured
        return data


config = Config()

#EOF