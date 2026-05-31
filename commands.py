"""Sistema de procesamiento de comandos MQTT.

Corregido para:
- mantener compatibilidad con tus comandos actuales
- trabajar con el modelo real de schedule del proyecto standalone
- soportar schedule y modbus sin romper el flujo actual
"""

from __future__ import annotations

from typing import Any, Dict

from logger import setup_logger
from models import (
    BATTERY_MODES,
    DAY_KEY_FROM_SPANISH,
    DAY_KEYS,
    ScheduleSlot,
)
from solplanet_client import (
    SolplanetClient,
    SolplanetClientError,
    SolplanetValidationError,
)

logger = setup_logger(__name__)


class CommandHandler:
    """Manejador de comandos MQTT."""

    VALID_MODES = {2, 3, 4, 5}
    VALID_MINUTES = {0, 30}

    def __init__(self, solplanet_client: SolplanetClient):
        self.client = solplanet_client

    # ============================================================
    # API PRINCIPAL
    # ============================================================

    def process_command(self, payload: Dict[str, Any]) -> bool:
        """Procesa un comando recibido vía MQTT."""
        try:
            if not isinstance(payload, dict):
                logger.error("❌ El comando recibido no es un diccionario válido")
                return False

            logger.info("📨 Procesando comando MQTT: %s", payload)

            # 1) Compatibilidad directa: modo simple
            if "mode" in payload and len(payload) == 1:
                mode = int(payload["mode"])
                logger.info("📥 Comando recibido: Cambiar modo a %s", mode)
                return self._set_battery_mode(mode)

            # 2) Compatibilidad: SOC simple
            if ("charge_max" in payload or "discharge_max" in payload) and not payload.get("action"):
                logger.info("📥 Comando recibido: Ajustar límites SOC")
                return self._set_soc_limits(payload)

            # 3) Compatibilidad: payload completo batería
            if payload.get("device") == 4 and payload.get("action") == "setbattery":
                logger.info("📥 Comando recibido: Configuración completa de batería")
                return self._set_full_battery_config(payload)

            # 4) Compatibilidad/nuevo: raw schedule completo
            if payload.get("device") == 4 and payload.get("action") == "setdefine":
                logger.info("📥 Comando recibido: Schedule completo raw")
                return self._set_full_schedule(payload)

            # 5) Router por acción explícita
            action = str(payload.get("action", "")).strip().lower()
            if action:
                return self._dispatch_action(action, payload)

            logger.warning("⚠️ Comando no reconocido: %s", payload)
            return False

        except SolplanetClientError as e:
            logger.error("❌ Error del cliente Solplanet procesando comando: %s", e)
            return False
        except Exception as e:
            logger.error("❌ Error procesando comando: %s", e)
            return False

    def _dispatch_action(self, action: str, payload: Dict[str, Any]) -> bool:
        routes = {
            "set_mode": self._action_set_mode,
            "set_battery_mode": self._action_set_mode,
            "set_soc": self._action_set_soc,
            "set_soc_limits": self._action_set_soc,
            "set_schedule": self._action_set_schedule,
            "set_schedule_power": self._action_set_schedule_power,
            "set_schedule_pin": self._action_set_schedule_pin,
            "set_schedule_pout": self._action_set_schedule_pout,
            "set_schedule_slot": self._action_set_schedule_slot,
            "clear_schedule": self._action_clear_schedule,
            "set_export_limit": self._action_set_export_limit,
            "modbus_write_single_holding_register": self._action_modbus_write_single_holding_register,
            "refresh": self._action_refresh,
            "refresh_state": self._action_refresh,
        }

        handler = routes.get(action)
        if handler is None:
            logger.warning("⚠️ Acción no soportada: %s", action)
            return False

        return handler(payload)

    # ============================================================
    # HELPERS DE VALIDACIÓN
    # ============================================================

    def _normalize_day_key(self, day_value: Any) -> str:
        if day_value is None:
            raise SolplanetValidationError("Falta el campo 'day'")

        day = str(day_value).strip()
        if not day:
            raise SolplanetValidationError("El campo 'day' está vacío")

        day_key = DAY_KEY_FROM_SPANISH.get(day.lower(), day)

        if day_key not in DAY_KEYS and day_key != "all":
            raise SolplanetValidationError(
                f"Día inválido: {day}. Valores válidos: all, {', '.join(DAY_KEYS)}"
            )

        return day_key

    def _validate_mode(self, mode: int) -> None:
        mode = int(mode)
        if mode not in self.VALID_MODES:
            raise SolplanetValidationError(
                f"Modo inválido: {mode}. Valores válidos: {sorted(self.VALID_MODES)}"
            )

    def _validate_soc_value(self, value: int, field_name: str) -> int:
        value = int(value)
        if not (0 <= value <= 100):
            raise SolplanetValidationError(
                f"{field_name} inválido: {value}. Debe estar entre 0 y 100"
            )
        return value

    def _validate_hour(self, value: Any, field_name: str) -> int:
        value = int(value)
        if not (0 <= value <= 23):
            raise SolplanetValidationError(
                f"{field_name} inválido: {value}. Debe estar entre 0 y 23"
            )
        return value

    def _validate_minute(self, value: Any, field_name: str) -> int:
        value = int(value)
        if value not in self.VALID_MINUTES:
            raise SolplanetValidationError(
                f"{field_name} inválido: {value}. Solo se admite 0 o 30"
            )
        return value

    def _validate_duration(self, value: Any) -> int:
        value = int(value)
        if not (1 <= value <= 4):
            raise SolplanetValidationError(
                f"duration inválido: {value}. Debe estar entre 1 y 4 horas"
            )
        return value

    def _validate_schedule_mode(self, mode: Any) -> str:
        mode = str(mode).strip().lower()
        if mode not in {"charge", "discharge"}:
            raise SolplanetValidationError(
                f"mode inválido para schedule: {mode}. Debe ser 'charge' o 'discharge'"
            )
        return mode

    def _build_slot_from_payload(self, payload: Dict[str, Any]) -> ScheduleSlot:
        start_hour = self._validate_hour(payload.get("start_hour"), "start_hour")
        start_minute = self._validate_minute(payload.get("start_minute"), "start_minute")
        duration = self._validate_duration(payload.get("duration"))
        mode = self._validate_schedule_mode(payload.get("mode"))

        try:
            slot = ScheduleSlot(
                start_hour=start_hour,
                start_minute=start_minute,
                duration=duration,
                mode=mode,
            )
            slot.validate()
            return slot
        except ValueError as e:
            raise SolplanetValidationError(str(e)) from e

    # ============================================================
    # COMANDOS BATERÍA
    # ============================================================

    def _set_battery_mode(self, mode: int) -> bool:
        self._validate_mode(mode)

        success = self.client.set_battery_work_mode(int(mode))

        if success:
            logger.info(
                "✅ Modo de batería cambiado a %s (%s)",
                mode,
                BATTERY_MODES.get(int(mode), "Desconocido"),
            )
        else:
            logger.error("❌ Fallo al cambiar modo de batería")

        return success

    def _set_full_battery_config(self, payload: Dict[str, Any]) -> bool:
        success = self.client.set_full_battery_config(payload)

        if success:
            logger.info("✅ Configuración completa de batería enviada")
        else:
            logger.error("❌ Fallo al enviar configuración completa")

        return success

    def _set_soc_limits(self, payload: Dict[str, Any]) -> bool:
        params: Dict[str, Any] = {}

        if "charge_max" in payload:
            params["charge_max"] = self._validate_soc_value(payload["charge_max"], "charge_max")

        if "discharge_max" in payload:
            params["discharge_max"] = self._validate_soc_value(payload["discharge_max"], "discharge_max")

        if not params:
            logger.warning("⚠️ No se especificaron límites SOC")
            return False

        success = self.client.set_battery_config(**params)

        if success:
            logger.info("✅ Límites SOC actualizados: %s", params)
        else:
            logger.error("❌ Fallo al actualizar límites SOC")

        return success

    # ============================================================
    # ROUTES DE ACCIÓN - BATERÍA
    # ============================================================

    def _action_set_mode(self, payload: Dict[str, Any]) -> bool:
        if "mode" not in payload:
            raise SolplanetValidationError("Falta el campo 'mode'")
        return self._set_battery_mode(int(payload["mode"]))

    def _action_set_soc(self, payload: Dict[str, Any]) -> bool:
        return self._set_soc_limits(payload)

    def _action_refresh(self, payload: Dict[str, Any]) -> bool:
        self.client.refresh()
        logger.info("✅ Refresh forzado ejecutado")
        return True

    # ============================================================
    # COMANDOS SCHEDULE
    # ============================================================

    def _set_full_schedule(self, payload: Dict[str, Any]) -> bool:
        value = payload.get("value")
        if not isinstance(value, dict):
            raise SolplanetValidationError(
                "Payload setdefine inválido: falta 'value' tipo dict"
            )

        success = self.client.set_schedule_slots(value)

        if success:
            logger.info("✅ Schedule completo enviado")
        else:
            logger.error("❌ Fallo al enviar schedule completo")

        return success

    def _action_set_schedule(self, payload: Dict[str, Any]) -> bool:
        return self._set_full_schedule(payload)

    def _action_set_schedule_power(self, payload: Dict[str, Any]) -> bool:
        pin = payload.get("pin")
        pout = payload.get("pout")

        if pin is None and pout is None:
            raise SolplanetValidationError("Debes indicar al menos 'pin' o 'pout'")

        success = self.client.set_schedule_power(
            pin=int(pin) if pin is not None else None,
            pout=int(pout) if pout is not None else None,
        )

        if success:
            logger.info("✅ Potencia schedule actualizada: pin=%s pout=%s", pin, pout)
        else:
            logger.error("❌ Fallo actualizando potencia schedule")

        return success

    def _action_set_schedule_pin(self, payload: Dict[str, Any]) -> bool:
        if "pin" not in payload:
            raise SolplanetValidationError("Falta el campo 'pin'")

        pin = int(payload["pin"])
        success = self.client.set_schedule_pin(pin)

        if success:
            logger.info("✅ Schedule Pin actualizado a %s", pin)
        else:
            logger.error("❌ Fallo actualizando Pin")

        return success

    def _action_set_schedule_pout(self, payload: Dict[str, Any]) -> bool:
        if "pout" not in payload:
            raise SolplanetValidationError("Falta el campo 'pout'")

        pout = int(payload["pout"])
        success = self.client.set_schedule_pout(pout)

        if success:
            logger.info("✅ Schedule Pout actualizado a %s", pout)
        else:
            logger.error("❌ Fallo actualizando Pout")

        return success

    def _action_clear_schedule(self, payload: Dict[str, Any]) -> bool:
        day = self._normalize_day_key(payload.get("day", "all"))

        success = self.client.clear_schedule(day=day)

        if success:
            logger.info("✅ Schedule limpiado para day=%s", day)
        else:
            logger.error("❌ Fallo limpiando schedule")

        return success

    def _action_set_schedule_slot(self, payload: Dict[str, Any]) -> bool:
        """Añade o reemplaza un slot en un día concreto.

        Formato:
        {
          "action": "set_schedule_slot",
          "day": "Mon",
          "start_hour": 12,
          "start_minute": 0,
          "duration": 4,
          "mode": "discharge"
        }
        """
        day = self._normalize_day_key(payload.get("day"))
        slot = self._build_slot_from_payload(payload)

        current = self.client.get_schedule(force=True)
        daily = current.get_day(day)
        existing_slots = list(daily.slots) if daily else []

        replaced = False
        for idx, existing in enumerate(existing_slots):
            if (
                existing.start_hour == slot.start_hour
                and existing.start_minute == slot.start_minute
            ):
                existing_slots[idx] = slot
                replaced = True
                break

        if not replaced:
            existing_slots.append(slot)

        try:
            ScheduleSlot.validate_slots(existing_slots)
        except ValueError as e:
            raise SolplanetValidationError(str(e)) from e

        success = self.client.set_schedule_day_slots(day, existing_slots)

        if success:
            logger.info("✅ Slot schedule actualizado para %s: %s", day, slot.human_readable())
        else:
            logger.error("❌ Fallo actualizando slot del schedule")

        return success

    # ============================================================
    # COMANDOS MODBUS
    # ============================================================

    def _action_modbus_write_single_holding_register(self, payload: Dict[str, Any]) -> bool:
        required = ["device_address", "register_address", "data_type", "value"]
        missing = [field for field in required if field not in payload]
        if missing:
            raise SolplanetValidationError(
                "Faltan campos para modbus_write_single_holding_register: "
                + ", ".join(missing)
            )

        result = self.client.modbus_write_single_holding_register(
            device_address=int(payload["device_address"]),
            register_address=int(payload["register_address"]),
            data_type=str(payload["data_type"]),
            value=int(payload["value"]),
            dry_run=bool(payload.get("dry_run", False)),
        )

        logger.info("✅ Modbus write ejecutado. Resultado: %s", result)
        return True

    # ============================================================
    # CONTROL DE EXPORTACIÓN
    # ============================================================

    def _action_set_export_limit(self, payload: Dict[str, Any]) -> bool:
        """
        Limita la exportación a red.

        Formato:
        {"action": "set_export_limit", "watts": 0}       → no exportar
        {"action": "set_export_limit", "watts": 2000}    → max 2000W
        {"action": "set_export_limit", "watts": -1}      → sin límite (libre)
        """
        watts = payload.get("watts")
        if watts is None:
            raise SolplanetValidationError("Falta el campo 'watts'")

        watts = int(watts)

        if watts < -1 or watts > 10000:
            raise SolplanetValidationError("watts debe ser -1 (sin límite) o 0-10000")

        if watts == -1:
            # Quitar límite
            value = {"target": 0, "regulate": 0, "enb_PF": 0, "target_PF": 0, "abs": 0, "offset": 0}
            logger.info("📤 Quitando límite de exportación (libre)")
        else:
            # Poner límite
            value = {"target": watts, "regulate": 10, "enb_PF": 0, "target_PF": 0, "abs": 1, "offset": 2}
            logger.info("📤 Limitando exportación a %sW", watts)

        success = self.client.set_meter_config(value)

        if success:
            logger.info("✅ Límite de exportación aplicado: %s",
                        "sin límite" if watts == -1 else f"{watts}W")
        else:
            logger.error("❌ Fallo aplicando límite de exportación")

        return success


__all__ = ["CommandHandler"]
