#cat > mqtt_client.py << 'EOF'
"""Cliente MQTT robusto con soporte de comandos y reconexión."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt

from logger import setup_logger

logger = setup_logger(__name__)


class MQTTClient:
    """Cliente MQTT robusto para publicación de estado y recepción de comandos."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None,
        keepalive: int = 60,
        qos: int = 1,
        availability_topic: Optional[str] = "solplanet/disponibilidad",
        availability_payload_online: str = "online",
        availability_payload_offline: str = "offline",
    ):
        """
        Args:
            host: Host del broker MQTT
            port: Puerto MQTT
            username: Usuario opcional
            password: Contraseña opcional
            client_id: ID de cliente opcional
            keepalive: Keepalive MQTT
            qos: QoS por defecto para publish/subscribe
            availability_topic: Topic de disponibilidad (opcional)
            availability_payload_online: Payload online
            availability_payload_offline: Payload offline
        """
        self.host = host
        self.port = int(port)
        self.keepalive = int(keepalive)
        self.qos = int(qos)

        self.availability_topic = availability_topic
        self.availability_payload_online = availability_payload_online
        self.availability_payload_offline = availability_payload_offline

        self._connected = False
        self._closing = False
        self._connect_called = False

        self._command_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._subscriptions: set[str] = set()
        self._last_published_payloads: dict[str, str] = {}
        self._lock = threading.RLock()

        # Compatibilidad con paho-mqtt 1.6.x
        self.client = mqtt.Client(client_id=client_id or "", clean_session=True)

        if username and password:
            self.client.username_pw_set(username, password)

        if self.availability_topic:
            self.client.will_set(
                self.availability_topic,
                payload=self.availability_payload_offline,
                qos=self.qos,
                retain=True,
            )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_publish = self._on_publish
        self.client.on_subscribe = self._on_subscribe
        self.client.on_log = self._on_log

        # Reconexión automática del cliente
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    # ============================================================
    # CALLBACKS MQTT
    # ============================================================

    def _on_connect(self, client, userdata, flags, rc):
        """Callback de conexión MQTT."""
        with self._lock:
            if rc == 0:
                self._connected = True
                logger.info("✅ Conectado a MQTT en %s:%s", self.host, self.port)

                # Re-suscribir a todos los topics
                for topic in sorted(self._subscriptions):
                    try:
                        result, _mid = self.client.subscribe(topic, qos=self.qos)
                        if result == mqtt.MQTT_ERR_SUCCESS:
                            logger.info("📥 Re-suscrito a %s", topic)
                        else:
                            logger.warning("⚠️ Error re-suscribiendo a %s: rc=%s", topic, result)
                    except Exception as e:
                        logger.error("❌ Error re-suscribiendo a %s: %s", topic, e)

                # Publicar availability online
                if self.availability_topic:
                    try:
                        self.client.publish(
                            self.availability_topic,
                            payload=self.availability_payload_online,
                            qos=self.qos,
                            retain=True,
                        )
                    except Exception as e:
                        logger.warning("⚠️ No se pudo publicar availability online: %s", e)

            else:
                self._connected = False
                logger.error("❌ Error conectando a MQTT: rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        """Callback de desconexión MQTT."""
        with self._lock:
            self._connected = False

        if self._closing:
            logger.info("MQTT desconectado correctamente")
            return

        if rc != 0:
            logger.warning("⚠️ MQTT desconectado inesperadamente (rc=%s). El loop intentará reconectar.", rc)
        else:
            logger.info("MQTT desconectado")

    def _on_message(self, client, userdata, msg):
        """Callback de mensajes recibidos."""
        try:
            topic = str(msg.topic)
            raw_payload = msg.payload.decode("utf-8", errors="replace").strip()

            logger.info("📨 MQTT recibido en %s", topic)
            logger.debug("Payload MQTT raw en %s: %s", topic, raw_payload)

            if not raw_payload:
                logger.warning("⚠️ Payload vacío en topic %s", topic)
                return

            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError as e:
                logger.error("❌ Error parseando JSON en %s: %s", topic, e)
                return

            if not isinstance(payload, dict):
                logger.error("❌ El payload recibido no es un objeto JSON: %s", payload)
                return

            if self._command_callback:
                self._command_callback(payload)
            else:
                logger.warning("⚠️ No hay callback de comandos configurado")

        except Exception as e:
            logger.error("❌ Error procesando mensaje MQTT: %s", e)

    def _on_publish(self, client, userdata, mid):
        """Callback al publicar."""
        logger.debug("📤 Publicación MQTT completada (mid=%s)", mid)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """Callback al suscribirse."""
        logger.debug("📥 Suscripción MQTT confirmada (mid=%s, qos=%s)", mid, granted_qos)

    def _on_log(self, client, userdata, level, buf):
        """Log interno de paho, solo para debug fuerte."""
        # No lo elevamos a info para no ensuciar logs
        logger.debug("MQTT log [%s]: %s", level, buf)

    # ============================================================
    # API PÚBLICA
    # ============================================================

    def connect(self) -> bool:
        """Conecta al broker MQTT e inicia loop."""
        try:
            with self._lock:
                self._closing = False
                self._connect_called = True

            self.client.connect(self.host, self.port, self.keepalive)
            self.client.loop_start()

            # Espera corta a conexión inicial
            wait_seconds = 5.0
            started = time.time()

            while time.time() - started < wait_seconds:
                if self.is_connected():
                    return True
                time.sleep(0.1)

            logger.warning("⚠️ MQTT connect iniciado pero no confirmado todavía")
            return False

        except Exception as e:
            logger.error("❌ Error conectando a MQTT: %s", e)
            return False

    def disconnect(self):
        """Desconecta del broker MQTT limpiamente."""
        try:
            with self._lock:
                self._closing = True

            if self._connected and self.availability_topic:
                try:
                    self.client.publish(
                        self.availability_topic,
                        payload=self.availability_payload_offline,
                        qos=self.qos,
                        retain=True,
                    )
                except Exception as e:
                    logger.warning("⚠️ No se pudo publicar availability offline: %s", e)

            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Desconectado de MQTT")

        except Exception as e:
            logger.error("❌ Error desconectando MQTT: %s", e)

    def is_connected(self) -> bool:
        """Indica si MQTT está conectado."""
        with self._lock:
            return self._connected

    def wait_until_connected(self, timeout: float = 10.0) -> bool:
        """Espera hasta que el broker confirme conexión."""
        start = time.time()
        while time.time() - start < timeout:
            if self.is_connected():
                return True
            time.sleep(0.1)
        return False

    def publish(
        self,
        topic: str,
        payload: dict,
        retain: bool = True,
        qos: Optional[int] = None,
        skip_if_unchanged: bool = False,
    ) -> bool:
        """
        Publica un objeto JSON en MQTT.

        Args:
            topic: Topic MQTT
            payload: dict serializable
            retain: retain flag
            qos: qos opcional
            skip_if_unchanged: evita republicar si el JSON no cambió
        """
        qos = self.qos if qos is None else int(qos)

        if not isinstance(payload, dict):
            logger.error("❌ publish() requiere un dict, recibido: %s", type(payload).__name__)
            return False

        if not topic:
            logger.error("❌ publish() requiere un topic válido")
            return False

        if not self.is_connected():
            logger.warning("⚠️ No conectado a MQTT, saltando publicación en %s", topic)
            return False

        try:
            message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

            if skip_if_unchanged:
                last = self._last_published_payloads.get(topic)
                if last == message:
                    logger.debug("⏭️ MQTT sin cambios en %s, se omite publicación", topic)
                    return True

            result = self.client.publish(topic, message, qos=qos, retain=retain)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self._last_published_payloads[topic] = message
                return True

            logger.error("❌ Error publicando en MQTT (%s): rc=%s", topic, result.rc)
            return False

        except Exception as e:
            logger.error("❌ Error publicando en MQTT: %s", e)
            return False

    def publish_raw(
        self,
        topic: str,
        payload: str,
        retain: bool = False,
        qos: Optional[int] = None,
    ) -> bool:
        """Publica un payload raw (texto)."""
        qos = self.qos if qos is None else int(qos)

        if not topic:
            logger.error("❌ publish_raw() requiere un topic válido")
            return False

        if not self.is_connected():
            logger.warning("⚠️ No conectado a MQTT, saltando publicación raw en %s", topic)
            return False

        try:
            result = self.client.publish(topic, payload, qos=qos, retain=retain)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error("❌ Error publicando raw en MQTT: %s", e)
            return False

    def subscribe(self, topic: str, qos: Optional[int] = None) -> bool:
        """Suscribe a un topic y lo conserva para re-suscripción automática."""
        qos = self.qos if qos is None else int(qos)

        if not topic:
            logger.error("❌ subscribe() requiere un topic válido")
            return False

        try:
            with self._lock:
                self._subscriptions.add(topic)

            if self.is_connected():
                result, _mid = self.client.subscribe(topic, qos=qos)
                if result == mqtt.MQTT_ERR_SUCCESS:
                    logger.info("📥 Suscrito a %s", topic)
                    return True

                logger.error("❌ Error suscribiendo a %s: rc=%s", topic, result)
                return False

            logger.info("📥 Suscripción registrada para %s (se aplicará al conectar)", topic)
            return True

        except Exception as e:
            logger.error("❌ Error suscribiendo a MQTT: %s", e)
            return False

    def unsubscribe(self, topic: str) -> bool:
        """Cancela suscripción a un topic."""
        if not topic:
            return False

        try:
            with self._lock:
                self._subscriptions.discard(topic)

            if self.is_connected():
                result, _mid = self.client.unsubscribe(topic)
                if result != mqtt.MQTT_ERR_SUCCESS:
                    logger.error("❌ Error cancelando suscripción a %s: rc=%s", topic, result)
                    return False

            logger.info("📪 Cancelada suscripción a %s", topic)
            return True

        except Exception as e:
            logger.error("❌ Error cancelando suscripción MQTT: %s", e)
            return False

    def set_command_callback(self, callback: Callable[[Dict[str, Any]], Any]):
        """Configura callback para comandos JSON."""
        self._command_callback = callback
        logger.info("✅ Callback de comandos configurado")

    def get_subscriptions(self) -> list[str]:
        """Devuelve lista de topics suscritos."""
        with self._lock:
            return sorted(self._subscriptions)

    def publish_availability(self, online: bool) -> bool:
        """Publica explícitamente estado online/offline."""
        if not self.availability_topic:
            return False

        payload = (
            self.availability_payload_online
            if online
            else self.availability_payload_offline
        )
        return self.publish_raw(
            self.availability_topic,
            payload=payload,
            retain=True,
            qos=self.qos,
        )


__all__ = ["MQTTClient"]
#EOF