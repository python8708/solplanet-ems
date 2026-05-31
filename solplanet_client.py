
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

import requests

from logger import setup_logger
from models import (
    BATTERY_MODES,
    BatteryConfig,
    BatteryData,
    DeviceDiscovery,
    DongleInfo,
    InverterData,
    InverterInfo,
    MeterData,
    MeterInfo,
    ScheduleConfig,
    ScheduleSlot,
    SystemSnapshot,
    SystemState,
)

logger = setup_logger(__name__)


class SolplanetClientError(Exception):
    """Error base del cliente Solplanet."""


class SolplanetRequestError(SolplanetClientError):
    """Error HTTP o de transporte."""


class SolplanetResponseError(SolplanetClientError):
    """Respuesta inválida o inesperada del dongle."""


class SolplanetValidationError(SolplanetClientError):
    """Error de validación de parámetros."""


class SolplanetClient:
    """Cliente HTTP standalone para Solplanet."""

    def __init__(
        self,
        base_url: str,
        battery_sn: Optional[str] = None,
        timeout: int = 8,
        retries: int = 3,
        retry_delay: float = 0.6,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.retries = int(retries)
        self.retry_delay = float(retry_delay)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SolplanetEMS/3.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        self._lock = threading.RLock()

        self._manual_battery_sn = battery_sn.strip() if battery_sn else None
        self._discovery_cache: Optional[DeviceDiscovery] = None
        self._schedule_cache: Optional[ScheduleConfig] = None
        self._battery_config_cache: Optional[BatteryConfig] = None
        self._snapshot_cache: Optional[SystemSnapshot] = None
        self._state_cache: Optional[SystemState] = None

    # ============================================================
    # UTILIDADES HTTP
    # ============================================================

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def _build_url(self, endpoint: str) -> str:
        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{self.base_url}{endpoint}"

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self.retry_delay * (2 ** max(0, attempt - 1)))

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        expect_json: bool = True,
    ) -> Any:
        url = self._build_url(endpoint)
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retries + 1):
            try:
                logger.debug(
                    "HTTP %s %s%s",
                    method.upper(),
                    url,
                    f" payload={payload}" if payload is not None else "",
                )

                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()

                if not expect_json:
                    return response.text

                text = response.text.strip()
                if not text:
                    raise SolplanetResponseError(f"Respuesta vacía en {endpoint}")

                try:
                    data = response.json()
                except Exception as exc:
                    raise SolplanetResponseError(
                        f"JSON inválido en {endpoint}: {text[:300]}"
                    ) from exc

                logger.debug("Respuesta %s: %s", endpoint, data)
                return data

            except requests.exceptions.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Error HTTP en %s intento %s/%s: %s",
                    endpoint,
                    attempt,
                    self.retries,
                    exc,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Error inesperado en %s intento %s/%s: %s",
                    endpoint,
                    attempt,
                    self.retries,
                    exc,
                )

            if attempt < self.retries:
                self._sleep_backoff(attempt)

        raise SolplanetRequestError(
            f"No se pudo completar {method.upper()} {endpoint}: {last_error}"
        )

    def _get_json(self, endpoint: str) -> Dict[str, Any]:
        data = self._request("GET", endpoint, expect_json=True)
        if not isinstance(data, dict):
            raise SolplanetResponseError(
                f"Se esperaba JSON objeto en {endpoint}, recibido: {type(data).__name__}"
            )
        return data

    def _post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._request("POST", endpoint, payload=payload, expect_json=True)
        if not isinstance(data, dict):
            raise SolplanetResponseError(
                f"Se esperaba JSON objeto en POST {endpoint}, recibido: {type(data).__name__}"
            )
        return data

    # ============================================================
    # HELPERS DE DISCOVERY
    # ============================================================

    @staticmethod
    def _extract_first_inverter(data: Dict[str, Any]) -> Dict[str, Any]:
        inv_list = data.get("inv")
        if not isinstance(inv_list, list) or not inv_list:
            raise SolplanetResponseError(
                "No se ha encontrado ningún inversor en getdev.cgi?device=2"
            )
        first = inv_list[0]
        if not isinstance(first, dict):
            raise SolplanetResponseError("La estructura de 'inv' no es válida")
        return first

    def discover_devices(self, force: bool = False) -> DeviceDiscovery:
        with self._lock:
            if self._discovery_cache is not None and not force:
                return self._discovery_cache

            dongle: Optional[DongleInfo] = None
            inverter: Optional[InverterInfo] = None
            meter: Optional[MeterInfo] = None
            battery: Optional[BatteryConfig] = None

            try:
                dongle_raw = self._get_json("/getdev.cgi?device=1")
                dongle = DongleInfo.from_api(dongle_raw)
            except Exception as exc:
                logger.warning("No se pudo leer info del dongle: %s", exc)

            inverter_raw = self._get_json("/getdev.cgi?device=2")
            inverter = InverterInfo.from_api(self._extract_first_inverter(inverter_raw))

            try:
                meter_raw = self._get_json("/getdev.cgi?device=3")
                meter = MeterInfo.from_api(meter_raw)
            except Exception as exc:
                logger.info("Meter no detectado o no accesible: %s", exc)

            battery_sn = self._manual_battery_sn or inverter.isn
            try:
                battery_raw = self._get_json(f"/getdev.cgi?device=4&sn={battery_sn}")
                battery = BatteryConfig.from_api(battery_raw)
                if not battery.sn:
                    battery.sn = battery_sn
            except Exception as exc:
                logger.info("Batería no detectada o no accesible: %s", exc)

            discovery = DeviceDiscovery(
                dongle=dongle,
                inverter=inverter,
                meter=meter,
                battery=battery,
            )

            self._discovery_cache = discovery
            self._battery_config_cache = battery

            logger.info(
                "Discovery completado: inverter_sn=%s has_meter=%s has_battery=%s",
                discovery.inverter_sn,
                discovery.has_meter,
                discovery.has_battery,
            )
            return discovery

    def get_discovery(self, force: bool = False) -> DeviceDiscovery:
        return self.discover_devices(force=force)

    def get_inverter_sn(self) -> str:
        discovery = self.discover_devices()
        if not discovery.inverter_sn:
            raise SolplanetResponseError("No se pudo obtener el SN del inversor")
        return discovery.inverter_sn

    def get_battery_sn(self) -> str:
        discovery = self.discover_devices()
        if self._manual_battery_sn:
            return self._manual_battery_sn
        if discovery.battery_sn:
            return discovery.battery_sn
        return self.get_inverter_sn()

    # ============================================================
    # LECTURAS CRUDAS
    # ============================================================

    def get_dongle_info(self, force: bool = False) -> Optional[DongleInfo]:
        discovery = self.discover_devices(force=force)
        return discovery.dongle

    def get_inverter_info(self, force: bool = False) -> InverterInfo:
        if force or not self._discovery_cache or not self._discovery_cache.inverter:
            self.discover_devices(force=True)
        discovery = self.discover_devices()
        if not discovery.inverter:
            raise SolplanetResponseError("No hay info del inversor")
        return discovery.inverter

    def get_meter_info(self, force: bool = False) -> Optional[MeterInfo]:
        if force:
            self.discover_devices(force=True)
        discovery = self.discover_devices()
        return discovery.meter

    def get_battery_info(
        self,
        sn: Optional[str] = None,
        force: bool = False,
    ) -> Optional[BatteryConfig]:
        with self._lock:
            if self._battery_config_cache is not None and not force and sn is None:
                return self._battery_config_cache

            use_sn = sn or self.get_battery_sn()

            try:
                raw = self._get_json(f"/getdev.cgi?device=4&sn={use_sn}")
            except Exception as exc:
                logger.warning("⚠️ battery_info fallback: %s", exc)

                if self._battery_config_cache is not None:
                    return self._battery_config_cache

                if force:
                    raise
                return None

            config = BatteryConfig.from_api(raw)
            if not config.sn:
                config.sn = use_sn

            self._battery_config_cache = config
            if self._discovery_cache is not None:
                self._discovery_cache.battery = config

            return config

    def get_battery_config(self, force: bool = False) -> Optional[BatteryConfig]:
        return self.get_battery_info(force=force)

    def get_inverter_data(self, sn: Optional[str] = None) -> InverterData:
        use_sn = sn or self.get_inverter_sn()
        raw = self._get_json(f"/getdevdata.cgi?device=2&sn={use_sn}")
        return InverterData.from_api(raw)

    def get_meter_data(self) -> Optional[MeterData]:
        try:
            raw = self._get_json("/getdevdata.cgi?device=3")
            return MeterData.from_api(raw)
        except Exception as exc:
            logger.info("Meter data no disponible: %s", exc)
            return None

    def get_battery_data(self, sn: Optional[str] = None) -> Optional[BatteryData]:
        use_sn = sn or self.get_battery_sn()
        try:
            raw = self._get_json(f"/getdevdata.cgi?device=4&sn={use_sn}")
            return BatteryData.from_api(raw)
        except Exception as exc:
            logger.info("Battery data no disponible: %s", exc)
            return None

    def get_schedule(self, force: bool = False) -> ScheduleConfig:
        with self._lock:
            if self._schedule_cache is not None and not force:
                return self._schedule_cache

            try:
                raw = self._get_json("/getdefine.cgi")
                schedule = ScheduleConfig.from_api(raw)
                self._schedule_cache = schedule
                return schedule
            except Exception as exc:
                logger.warning("⚠️ get_schedule fallback: %s", exc)

                if self._schedule_cache is not None:
                    return self._schedule_cache

                raise

    # ============================================================
    # SNAPSHOT / ESTADO AGREGADO
    # ============================================================

    def get_snapshot(self, force_refresh: bool = False) -> SystemSnapshot:
        with self._lock:
            if self._snapshot_cache is not None and not force_refresh:
                return self._snapshot_cache

            if self._discovery_cache is not None:
                discovery = self._discovery_cache
            else:
                discovery = self.discover_devices(force=True)

            inverter_info = discovery.inverter
            meter_info = discovery.meter

            try:
                battery_config = self.get_battery_info(force=False)
            except Exception as exc:
                logger.debug("Battery config fallback: %s", exc)
                battery_config = self._battery_config_cache

            try:
                schedule = self.get_schedule(force=False)
            except Exception as exc:
                logger.debug("Schedule fallback: %s", exc)
                schedule = self._schedule_cache

            if inverter_info is None:
                raise SolplanetResponseError(
                    "No se pudo leer información del inversor"
                )

            inverter_data = self.get_inverter_data(sn=inverter_info.isn)

            try:
                meter_data = self.get_meter_data() if discovery.has_meter else None
            except Exception as exc:
                logger.debug("Meter fallback: %s", exc)
                meter_data = None

            try:
                battery_data = (
                    self.get_battery_data(sn=self.get_battery_sn())
                    if discovery.has_battery
                    else None
                )
            except Exception as exc:
                logger.debug("Battery data fallback: %s", exc)
                battery_data = None

            snapshot = SystemSnapshot(
                inverter_info=inverter_info,
                inverter_data=inverter_data,
                meter_info=meter_info,
                meter_data=meter_data,
                battery_config=battery_config,
                battery_data=battery_data,
                schedule=schedule,
            )

            self._snapshot_cache = snapshot
            self._state_cache = SystemState.from_snapshot(snapshot)
            return snapshot

    def get_state(self, force_refresh: bool = False) -> SystemState:
        with self._lock:
            if self._state_cache is not None and not force_refresh:
                return self._state_cache
            snapshot = self.get_snapshot(force_refresh=force_refresh)
            self._state_cache = SystemState.from_snapshot(snapshot)
            return self._state_cache

    def refresh(self, settle_seconds: float = 2.5) -> SystemState:
        with self._lock:
            if settle_seconds > 0:
                time.sleep(settle_seconds)

            self._snapshot_cache = None
            self._state_cache = None
            self._schedule_cache = None
            self._battery_config_cache = None

        return self.get_state(force_refresh=True)

    # ============================================================
    # ESCRITURAS DE BATERÍA
    # ============================================================

    def _post_setting(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._post_json("/setting.cgi", payload)
        logger.info("Configuración enviada a setting.cgi: %s", payload)
        logger.debug("Respuesta setting.cgi: %s", response)
        return response

    def set_meter_config(self, value: Dict[str, Any]) -> bool:
        """Configura parámetros del meter (export limit, PF, etc.)."""
        payload = {"device": 3, "action": "setmeter", "value": value}
        response = self._post_setting(payload)
        return response.get("dat") == "ok"

    def set_full_battery_config(
        self,
        payload: Dict[str, Any],
        refresh: bool = True,
    ) -> bool:
        if payload.get("device") != 4 or payload.get("action") != "setbattery":
            raise SolplanetValidationError(
                "Payload inválido para batería: se esperaba {'device':4,'action':'setbattery',...}"
            )

        value = payload.get("value")
        if not isinstance(value, dict):
            raise SolplanetValidationError(
                "Payload de batería sin campo 'value' válido"
            )

        self._post_setting(payload)

        try:
            updated = BatteryConfig.from_api(value)
            if not updated.isn:
                updated.isn = value.get("sn", self.get_battery_sn())
            if not updated.sn:
                updated.sn = value.get("sn", self.get_battery_sn())
            self._battery_config_cache = updated
            if self._discovery_cache is not None:
                self._discovery_cache.battery = updated
        except Exception:
            self._battery_config_cache = None

        if refresh:
            self.refresh(settle_seconds=2.5)
        return True

    def set_battery_config(
        self,
        *,
        type: Optional[int] = None,
        mod_r: Optional[int] = None,
        sn: Optional[str] = None,
        discharge_max: Optional[int] = None,
        charge_max: Optional[int] = None,
        muf: Optional[int] = None,
        mod: Optional[int] = None,
        num: Optional[int] = None,
        refresh: bool = True,
    ) -> bool:
        current: Optional[BatteryConfig] = None

        try:
            current = self.get_battery_info(force=True)
        except Exception as exc:
            logger.warning(
                "No se pudo releer battery info actual, usando caché: %s",
                exc,
            )
            current = self._battery_config_cache

        if current is None and self._discovery_cache is not None:
            current = self._discovery_cache.battery

        if current is None:
            raise SolplanetResponseError(
                "No se pudo obtener configuración actual de batería ni desde caché"
            )

        value = {
            "type": int(type if type is not None else current.type),
            "mod_r": int(mod_r if mod_r is not None else current.mod_r),
            "sn": str(
                sn if sn is not None else (current.sn or current.isn or self.get_battery_sn())
            ),
            "discharge_max": int(
                discharge_max if discharge_max is not None else current.discharge_max
            ),
            "charge_max": int(
                charge_max if charge_max is not None else current.charge_max
            ),
            "muf": muf if muf is not None else current.muf,
            "mod": mod if mod is not None else current.mod,
            "num": num if num is not None else current.num,
        }

        payload = {
            "device": 4,
            "action": "setbattery",
            "value": value,
        }

        self._post_setting(payload)

        updated = BatteryConfig.from_api(value)
        if not updated.isn:
            updated.isn = value.get("sn", self.get_battery_sn())
        if not updated.sn:
            updated.sn = value.get("sn", self.get_battery_sn())

        self._battery_config_cache = updated
        if self._discovery_cache is not None:
            self._discovery_cache.battery = updated

        if refresh:
            self.refresh(settle_seconds=2.5)
        return True

    def set_battery_work_mode(self, mode: int, refresh: bool = True) -> bool:
        if mode not in BATTERY_MODES:
            raise SolplanetValidationError(f"Modo de batería no soportado: {mode}")

        logger.info("Cambiando modo batería a %s (%s)", mode, BATTERY_MODES[mode])
        return self.set_battery_config(mod_r=mode, refresh=refresh)

    def set_battery_soc_min(self, soc_min: int, refresh: bool = True) -> bool:
        if not 0 <= int(soc_min) <= 100:
            raise SolplanetValidationError("soc_min debe estar entre 0 y 100")
        logger.info("Cambiando SOC mínimo / discharge_max a %s", soc_min)
        return self.set_battery_config(discharge_max=int(soc_min), refresh=refresh)

    def set_battery_soc_max(self, soc_max: int, refresh: bool = True) -> bool:
        if not 0 <= int(soc_max) <= 100:
            raise SolplanetValidationError("soc_max debe estar entre 0 y 100")
        logger.info("Cambiando SOC máximo / charge_max a %s", soc_max)
        return self.set_battery_config(charge_max=int(soc_max), refresh=refresh)

    # ============================================================
    # SCHEDULE
    # ============================================================

    @staticmethod
    def _validate_schedule_power(value: int, field_name: str) -> None:
        if int(value) < 0:
            raise SolplanetValidationError(f"{field_name} no puede ser negativo")

    @staticmethod
    def _normalize_schedule_slots_for_day(slots: list[ScheduleSlot]) -> list[int]:
        raw_values = [slot.to_raw() for slot in slots]
        if len(raw_values) > 6:
            raise SolplanetValidationError("Máximo 6 slots por día")
        while len(raw_values) < 6:
            raw_values.append(0)
        return raw_values[:6]

    def _schedule_to_setting_payload(
        self,
        schedule: ScheduleConfig,
    ) -> Dict[str, Any]:
        value = {
            "Pin": int(schedule.pin),
            "Pout": int(schedule.pout),
        }

        for day_key, daily in schedule.days.items():
            value[day_key] = self._normalize_schedule_slots_for_day(daily.slots)

        for day_key in ["Sun", "Mon", "Tus", "Wen", "Thu", "Fri", "Sat"]:
            value.setdefault(day_key, [0, 0, 0, 0, 0, 0])

        return {
            "device": 4,
            "action": "setdefine",
            "value": value,
        }

    def set_schedule(self, schedule: ScheduleConfig, refresh: bool = True) -> bool:
        self._validate_schedule_power(schedule.pin, "Pin")
        self._validate_schedule_power(schedule.pout, "Pout")

        payload = self._schedule_to_setting_payload(schedule)
        self._post_setting(payload)
        self._schedule_cache = schedule

        if refresh:
            self.refresh(settle_seconds=2.5)
        return True

    def set_schedule_power(
        self,
        pin: Optional[int] = None,
        pout: Optional[int] = None,
        refresh: bool = True,
    ) -> bool:
        current = self.get_schedule(force=True)
        new_schedule = ScheduleConfig(
            pin=int(pin if pin is not None else current.pin),
            pout=int(pout if pout is not None else current.pout),
            days=current.days,
        )
        logger.info(
            "Actualizando potencia schedule: Pin=%s Pout=%s",
            new_schedule.pin,
            new_schedule.pout,
        )
        return self.set_schedule(new_schedule, refresh=refresh)

    def set_schedule_pin(self, pin: int, refresh: bool = True) -> bool:
        return self.set_schedule_power(pin=int(pin), pout=None, refresh=refresh)

    def set_schedule_pout(self, pout: int, refresh: bool = True) -> bool:
        return self.set_schedule_power(pin=None, pout=int(pout), refresh=refresh)

    def set_schedule_slots(
        self,
        raw_schedule: Dict[str, Any],
        refresh: bool = True,
    ) -> bool:
        if not isinstance(raw_schedule, dict):
            raise SolplanetValidationError("raw_schedule debe ser un diccionario")

        payload = {
            "device": 4,
            "action": "setdefine",
            "value": raw_schedule,
        }

        self._post_setting(payload)
        self._schedule_cache = None

        if refresh:
            self.refresh(settle_seconds=2.5)
        return True

    def set_schedule_day_slots(
        self,
        day_key: str,
        slots: list[ScheduleSlot],
        refresh: bool = True,
    ) -> bool:
        current = self.get_schedule(force=True)
        current.set_day_slots(day_key, slots)
        logger.info("Actualizando slots del día %s (%s slots)", day_key, len(slots))
        return self.set_schedule(current, refresh=refresh)

    def clear_schedule(self, day: str = "all", refresh: bool = True) -> bool:
        current = self.get_schedule(force=True)

        target_days = (
            ["Sun", "Mon", "Tus", "Wen", "Thu", "Fri", "Sat"]
            if str(day).lower() == "all"
            else [day]
        )

        for day_key in target_days:
            current.set_day_slots(day_key, [])

        logger.info("Schedule limpiado para: %s", target_days)
        return self.set_schedule(current, refresh=refresh)

    # ============================================================
    # MODBUS ENCAPSULADO
    # ============================================================

    @staticmethod
    def _modbus_data_type_code(data_type: str) -> int:
        mapping = {
            "B16": 0,
            "B32": 1,
            "S16": 2,
            "U16": 3,
            "S32": 4,
            "U32": 5,
            "E16": 6,
            "STRING": 7,
        }
        key = str(data_type).upper()
        if key not in mapping:
            raise SolplanetValidationError(
                f"Tipo Modbus no soportado: {data_type}"
            )
        return mapping[key]

    def modbus_write_single_holding_register(
        self,
        *,
        device_address: int,
        register_address: int,
        data_type: str,
        value: int,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "action": "write_single_holding_register",
            "device_address": int(device_address),
            "register_address": int(register_address),
            "data_type": self._modbus_data_type_code(data_type),
            "value": int(value),
            "dry_run": bool(dry_run),
        }

        logger.info(
            "Modbus write: device=%s register=%s type=%s value=%s dry_run=%s",
            device_address,
            register_address,
            data_type,
            value,
            dry_run,
        )
        return self._post_json("/fdbg.cgi", payload)

    # ============================================================
    # SERIALIZACIÓN / DEBUG
    # ============================================================

    def get_state_dict(self, force_refresh: bool = False) -> Dict[str, Any]:
        return self.get_state(force_refresh=force_refresh).to_dict()

    def get_snapshot_dict(self, force_refresh: bool = False) -> Dict[str, Any]:
        return self.get_snapshot(force_refresh=force_refresh).to_dict()

    def export_debug_bundle(self, force_refresh: bool = True) -> Dict[str, Any]:
        discovery = self.get_discovery(force=force_refresh)
        snapshot = self.get_snapshot(force_refresh=force_refresh)
        state = self.get_state(force_refresh=False)

        return {
            "base_url": self.base_url,
            "discovery": discovery.to_dict(),
            "snapshot": snapshot.to_dict(),
            "state": state.to_dict(),
        }

    def export_debug_bundle_json(self, force_refresh: bool = True) -> str:
        return json.dumps(
            self.export_debug_bundle(force_refresh=force_refresh),
            ensure_ascii=False,
            indent=2,
        )


__all__ = [
    "SolplanetClient",
    "SolplanetClientError",
    "SolplanetRequestError",
    "SolplanetResponseError",
    "SolplanetValidationError",
]
