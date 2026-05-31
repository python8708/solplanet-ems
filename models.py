"""Modelos de datos del sistema EMS Solplanet.

Archivo corregido y alineado con:
- el cliente standalone actual (`solplanet_client.py`)
- la lógica de schedule de la integración original de Home Assistant
- la publicación MQTT que quieres usar en HA

Puntos clave:
- ScheduleSlot usa start_hour, start_minute, duration y mode
- duración válida: 1..4 horas
- minutos válidos: 00 o 30
- máximo 6 slots por día
- se publica schedule_summary para HA
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================
# CONSTANTES DE MODOS / ESTADOS
# ============================================================

BATTERY_MODES: Dict[int, str] = {
    2: "Autoconsumo",
    3: "Reserva",
    4: "Custom",
    5: "Time of Use",
    6: "Off-grid",
}

BATTERY_COMMUNICATION_STATUS: Dict[int, str] = {
    10: "Normal",
    11: "Batería virtual",
}

BATTERY_STATUS: Dict[int, str] = {
    1: "Idle",
    2: "Charging",
    3: "Discharging",
    4: "Fault",
}

INVERTER_STATUS: Dict[int, str] = {
    0: "Desconocido",
    1: "Normal",
    2: "Standby",
    3: "Fallo",
}

INVERTER_ERRORS: Dict[int, str] = {
    0: "Sin error",
    1: "Fallo de comunicación M-S",
    2: "Fallo EEPROM",
    3: "Fallo de relé",
    4: "Inyección DC alta",
    5: "Autotest fallido",
    6: "Bus DC alto",
    7: "Referencia interna anómala",
    8: "Fallo AC HCT",
    9: "Fallo GFCI",
    10: "Fallo de dispositivo",
    11: "Versión M-S incompatible",
    32: "ROCOF fault",
    33: "Frecuencia fuera de rango",
    34: "Voltaje AC fuera de rango",
    35: "Pérdida de red",
    36: "Fallo GFCI",
    37: "Sobrevoltaje FV",
    38: "Fallo de aislamiento",
    39: "Ventilador bloqueado",
    40: "Sobretemperatura del inversor",
    305: "Inversor offline",
    2000: "Sobrecorriente de descarga",
    2001: "Sobrecarga",
    2002: "Batería desconectada",
    2003: "Batería baja tensión",
    2004: "Capacidad batería baja",
    2005: "Sobretensión batería",
    2006: "Tensión de red baja",
    2007: "Tensión de red baja",
    2008: "Frecuencia de red anómala",
}

# Orden útil para payload raw del schedule
DAY_KEYS: List[str] = ["Sun", "Mon", "Tus", "Wen", "Thu", "Fri", "Sat"]

# Orden útil para mostrar en HA / resumen humano
DAY_KEYS_HUMAN: List[str] = ["Mon", "Tus", "Wen", "Thu", "Fri", "Sat", "Sun"]

DAY_NAME_MAP: Dict[str, str] = {
    "Sun": "Domingo",
    "Mon": "Lunes",
    "Tus": "Martes",
    "Wen": "Miércoles",
    "Thu": "Jueves",
    "Fri": "Viernes",
    "Sat": "Sábado",
}

DAY_KEY_FROM_SPANISH: Dict[str, str] = {
    "domingo": "Sun",
    "lunes": "Mon",
    "martes": "Tus",
    "miercoles": "Wen",
    "miércoles": "Wen",
    "jueves": "Thu",
    "viernes": "Fri",
    "sabado": "Sat",
    "sábado": "Sat",
    "sun": "Sun",
    "mon": "Mon",
    "tus": "Tus",
    "wen": "Wen",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
}


# ============================================================
# HELPERS GENERALES
# ============================================================

def _now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)


# ============================================================
# HELPERS DE SCHEDULE (FORMATO REAL SOLPLANET)
# ============================================================

def decode_schedule_word(value: int) -> Dict[str, Any]:
    """Decodifica el entero raw del schedule del inversor.

    Formato observado en la integración original:
    - bit 0: 1=discharge / 0=charge
    - bits 14..15: duración-1 (1..4 horas)
    - bit 17: 1 si empieza en :30
    - bits 24..: hora de inicio
    """
    value = int(value or 0)

    if value == 0:
        return {
            "raw": 0,
            "enabled": False,
            "start_hour": 0,
            "start_minute": 0,
            "duration": 0,
            "mode": "charge",
            "end_hour": 0,
            "end_minute": 0,
        }

    discharge_bit = value & 0x1
    duration_bits = (value >> 14) & 0x3
    half_hour_bit = (value >> 17) & 0x1
    hour_bits = value >> 24

    start_hour = int(hour_bits)
    start_minute = 30 if half_hour_bit else 0
    duration = int(duration_bits) + 1
    mode = "discharge" if discharge_bit else "charge"

    end_hour = (start_hour + duration) % 24
    end_minute = start_minute

    return {
        "raw": value,
        "enabled": True,
        "start_hour": start_hour,
        "start_minute": start_minute,
        "duration": duration,
        "mode": mode,
        "end_hour": end_hour,
        "end_minute": end_minute,
    }


def encode_schedule_word(
    enabled: bool,
    start_hour: int,
    start_minute: int,
    duration: Optional[int] = None,
    mode: Optional[str] = None,
    end_hour: Optional[int] = None,
    end_minute: Optional[int] = None,
) -> int:
    """Codifica un slot al entero raw del schedule.

    Compatibilidad:
    - preferido: start_hour + start_minute + duration + mode
    - fallback compatible: start_hour + start_minute + end_hour + end_minute
    """
    if not enabled:
        return 0

    start_hour = int(start_hour)
    start_minute = int(start_minute)

    if start_minute not in (0, 30):
        raise ValueError("Minutes must be 0 or 30")

    if not (0 <= start_hour <= 23):
        raise ValueError("Hour must be between 0 and 23")

    if duration is None:
        if end_hour is None or end_minute is None:
            raise ValueError("Either duration or end_hour/end_minute must be provided")
        end_hour = int(end_hour)
        end_minute = int(end_minute)
        if end_minute != start_minute:
            raise ValueError("end_minute must match start_minute in Solplanet schedule")
        duration = (end_hour - start_hour) % 24
        if duration == 0:
            duration = 24

    duration = int(duration)
    if not (1 <= duration <= 4):
        raise ValueError("Duration must be between 1 and 4 hours")

    mode = str(mode or "charge").strip().lower()
    if mode not in {"charge", "discharge"}:
        raise ValueError("mode must be 'charge' or 'discharge'")

    BASE = 0x3C02
    HOUR = 0x1000000
    HALF = 0x1E0000
    DURATION = 0x3C00

    return (
        BASE
        + (start_hour * HOUR)
        + ((start_minute // 30) * HALF)
        + ((duration - 1) * DURATION)
        + (1 if mode == "discharge" else 0)
    )


# ============================================================
# MODELOS DE DESCUBRIMIENTO / INFO
# ============================================================

@dataclass(slots=True)
class DongleInfo:
    psn: str = ""
    key: str = ""
    typ: int = 0
    nam: str = ""
    mod: str = ""
    muf: str = ""
    brd: str = ""
    hw: str = ""
    sw: str = ""
    wsw: str = ""
    protocol: str = ""
    tim: str = ""

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "DongleInfo":
        return cls(
            psn=str(data.get("psn", "")).strip(),
            key=str(data.get("key", "")).strip(),
            typ=int(data.get("typ", 0) or 0),
            nam=str(data.get("nam", "")).strip(),
            mod=str(data.get("mod", "")).strip(),
            muf=str(data.get("muf", "")).strip(),
            brd=str(data.get("brd", "")).strip(),
            hw=str(data.get("hw", "")).strip(),
            sw=str(data.get("sw", "")).strip(),
            wsw=str(data.get("wsw", "")).strip(),
            protocol=str(data.get("protocol", "")).strip(),
            tim=str(data.get("tim", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InverterInfo:
    isn: str = ""
    add: int = 0
    safety: int = 0
    rate: int = 0
    msw: str = ""
    ssw: str = ""
    tsw: str = ""
    pac: int = 0
    etd: int = 0
    eto: int = 0
    err: int = 0
    cmv: str = ""
    mty: int = 0
    mdl: str = ""
    nam: str = ""
    muf: str = ""
    ver: str = ""
    sn: str = ""

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "InverterInfo":
        return cls(
            isn=str(data.get("isn", "")).strip(),
            add=int(data.get("add", 0) or 0),
            safety=int(data.get("safety", 0) or 0),
            rate=int(data.get("rate", 0) or 0),
            msw=str(data.get("msw", "")).strip(),
            ssw=str(data.get("ssw", "")).strip(),
            tsw=str(data.get("tsw", "")).strip(),
            pac=int(data.get("pac", 0) or 0),
            etd=int(data.get("etd", 0) or 0),
            eto=int(data.get("eto", 0) or 0),
            err=int(data.get("err", 0) or 0),
            cmv=str(data.get("cmv", "")).strip(),
            mty=int(data.get("mty", 0) or 0),
            mdl=str(data.get("mdl", "")).strip(),
            nam=str(data.get("nam", "")).strip(),
            muf=str(data.get("muf", "")).strip(),
            ver=str(data.get("ver", "")).strip(),
            sn=str(data.get("sn", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MeterInfo:
    mod: int = 0
    enb: int = 0
    exp_m: int = 0
    regulate: int = 0
    enb_pf: int = 0
    target_pf: int = 0
    total_pac: int = 0
    total_fac: int = 0
    meter_pac: int = 0
    sn: str = ""
    manufactory: str = ""
    type: str = ""
    name: str = ""
    model: int = 0
    abs: int = 0
    offset: int = 0

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "MeterInfo":
        return cls(
            mod=int(data.get("mod", 0) or 0),
            enb=int(data.get("enb", 0) or 0),
            exp_m=int(data.get("exp_m", 0) or 0),
            regulate=int(data.get("regulate", 0) or 0),
            enb_pf=int(data.get("enb_PF", 0) or 0),
            target_pf=int(data.get("target_PF", 0) or 0),
            total_pac=int(data.get("total_pac", 0) or 0),
            total_fac=int(data.get("total_fac", 0) or 0),
            meter_pac=int(data.get("meter_pac", 0) or 0),
            sn=str(data.get("sn", "")).strip(),
            manufactory=str(data.get("manufactory", "")).strip(),
            type=str(data.get("type", "")).strip(),
            name=str(data.get("name", "")).strip(),
            model=int(data.get("model", 0) or 0),
            abs=int(data.get("abs", 0) or 0),
            offset=int(data.get("offset", 0) or 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BatteryConfig:
    isn: str = ""
    stu_r: int = 0
    type: int = 1
    mod_r: int = 2
    muf: Optional[int] = None
    mod: Optional[int] = None
    num: Optional[int] = None
    charging: int = 0
    charge_max: int = 100
    discharge_max: int = 10
    sn: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "BatteryConfig":
        return cls(
            isn=str(data.get("isn", "")).strip(),
            stu_r=int(data.get("stu_r", 0) or 0),
            type=int(data.get("type", 1) or 1),
            mod_r=int(data.get("mod_r", 2) or 2),
            muf=data.get("muf"),
            mod=data.get("mod"),
            num=data.get("num"),
            charging=int(data.get("charging", 0) or 0),
            charge_max=int(data.get("charge_max", 100) or 100),
            discharge_max=int(data.get("discharge_max", 10) or 10),
            sn=data.get("sn"),
        )

    @property
    def mode_name(self) -> str:
        return BATTERY_MODES.get(self.mod_r, f"Desconocido ({self.mod_r})")

    def to_setting_payload(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "type": self.type,
            "mod_r": self.mod_r,
            "charge_max": self.charge_max,
            "discharge_max": self.discharge_max,
        }
        if self.sn is not None:
            value["sn"] = self.sn
        if self.muf is not None:
            value["muf"] = self.muf
        if self.mod is not None:
            value["mod"] = self.mod
        if self.num is not None:
            value["num"] = self.num

        return {
            "device": 4,
            "action": "setbattery",
            "value": value,
        }

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["mode_name"] = self.mode_name
        return data


@dataclass(slots=True)
class DeviceDiscovery:
    dongle: Optional[DongleInfo] = None
    inverter: Optional[InverterInfo] = None
    meter: Optional[MeterInfo] = None
    battery: Optional[BatteryConfig] = None

    @property
    def inverter_sn(self) -> str:
        return self.inverter.isn if self.inverter else ""

    @property
    def battery_sn(self) -> str:
        if self.battery and self.battery.sn:
            return str(self.battery.sn)
        return self.inverter_sn

    @property
    def has_meter(self) -> bool:
        return self.meter is not None

    @property
    def has_battery(self) -> bool:
        return self.battery is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dongle": self.dongle.to_dict() if self.dongle else None,
            "inverter": self.inverter.to_dict() if self.inverter else None,
            "meter": self.meter.to_dict() if self.meter else None,
            "battery": self.battery.to_dict() if self.battery else None,
            "has_meter": self.has_meter,
            "has_battery": self.has_battery,
            "inverter_sn": self.inverter_sn,
            "battery_sn": self.battery_sn,
        }


# ============================================================
# MODELOS DE DATOS EN TIEMPO REAL
# ============================================================

@dataclass(slots=True)
class InverterData:
    flg: int = 0
    tim: str = ""
    tmp: int = 0
    fac: int = 0
    pac: int = 0
    sac: int = 0
    qac: int = 0
    eto: int = 0
    etd: int = 0
    hto: int = 0
    pf: int = 0
    wan: int = 0
    err: int = 0
    stu: int = 0
    vac: List[int] = field(default_factory=list)
    iac: List[int] = field(default_factory=list)
    vpv: List[int] = field(default_factory=list)
    ipv: List[int] = field(default_factory=list)
    str: List[int] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "InverterData":
        return cls(
            flg=int(data.get("flg", 0) or 0),
            tim=str(data.get("tim", "")).strip(),
            tmp=int(data.get("tmp", 0) or 0),
            fac=int(data.get("fac", 0) or 0),
            pac=int(data.get("pac", 0) or 0),
            sac=int(data.get("sac", 0) or 0),
            qac=int(data.get("qac", 0) or 0),
            eto=int(data.get("eto", 0) or 0),
            etd=int(data.get("etd", 0) or 0),
            hto=int(data.get("hto", 0) or 0),
            pf=int(data.get("pf", 0) or 0),
            wan=int(data.get("wan", 0) or 0),
            err=int(data.get("err", 0) or 0),
            stu=int(data.get("stu", 0) or 0),
            vac=[int(x or 0) for x in _safe_list(data.get("vac"))],
            iac=[int(x or 0) for x in _safe_list(data.get("iac"))],
            vpv=[int(x or 0) for x in _safe_list(data.get("vpv"))],
            ipv=[int(x or 0) for x in _safe_list(data.get("ipv"))],
            str=[int(x or 0) for x in _safe_list(data.get("str"))],
        )

    @property
    def temperature_c(self) -> float:
        return self.tmp / 10.0

    @property
    def frequency_hz(self) -> float:
        return self.fac / 100.0

    @property
    def power_factor(self) -> float:
        return self.pf / 100.0

    @property
    def ac_voltage_v(self) -> Optional[float]:
        return self.vac[0] / 10.0 if self.vac else None

    @property
    def ac_current_a(self) -> Optional[float]:
        return self.iac[0] / 10.0 if self.iac else None

    @property
    def pv1_voltage_v(self) -> Optional[float]:
        return self.vpv[0] / 10.0 if len(self.vpv) >= 1 else None

    @property
    def pv2_voltage_v(self) -> Optional[float]:
        return self.vpv[1] / 10.0 if len(self.vpv) >= 2 else None

    @property
    def pv1_current_a(self) -> Optional[float]:
        return self.ipv[0] / 100.0 if len(self.ipv) >= 1 else None

    @property
    def pv2_current_a(self) -> Optional[float]:
        return self.ipv[1] / 100.0 if len(self.ipv) >= 2 else None

    @property
    def pv1_power_w(self) -> Optional[int]:
        if self.pv1_voltage_v is None or self.pv1_current_a is None:
            return None
        return int(round(self.pv1_voltage_v * self.pv1_current_a))

    @property
    def pv2_power_w(self) -> Optional[int]:
        if self.pv2_voltage_v is None or self.pv2_current_a is None:
            return None
        return int(round(self.pv2_voltage_v * self.pv2_current_a))

    @property
    def total_pv_power_w(self) -> int:
        powers = [p for p in (self.pv1_power_w, self.pv2_power_w) if p is not None]
        return int(sum(powers)) if powers else max(0, self.pac)

    @property
    def status_name(self) -> str:
        return INVERTER_STATUS.get(self.stu, f"Desconocido ({self.stu})")

    @property
    def error_name(self) -> str:
        return INVERTER_ERRORS.get(self.err, f"Error desconocido ({self.err})")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "temperature_c": round(self.temperature_c, 1),
                "frequency_hz": round(self.frequency_hz, 2),
                "power_factor": round(self.power_factor, 2),
                "ac_voltage_v": _round_or_none(self.ac_voltage_v, 1),
                "ac_current_a": _round_or_none(self.ac_current_a, 1),
                "pv1_voltage_v": _round_or_none(self.pv1_voltage_v, 1),
                "pv2_voltage_v": _round_or_none(self.pv2_voltage_v, 1),
                "pv1_current_a": _round_or_none(self.pv1_current_a, 1),
                "pv2_current_a": _round_or_none(self.pv2_current_a, 1),
                "pv1_power_w": self.pv1_power_w,
                "pv2_power_w": self.pv2_power_w,
                "total_pv_power_w": self.total_pv_power_w,
                "status_name": self.status_name,
                "error_name": self.error_name,
            }
        )
        return data


@dataclass(slots=True)
class MeterData:
    flg: int = 0
    tim: str = ""
    pac: int = 0
    itd: int = 0
    otd: int = 0
    iet: int = 0
    oet: int = 0
    mod: int = 0
    enb: int = 0

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "MeterData":
        return cls(
            flg=int(data.get("flg", 0) or 0),
            tim=str(data.get("tim", "")).strip(),
            pac=int(data.get("pac", 0) or 0),
            itd=int(data.get("itd", 0) or 0),
            otd=int(data.get("otd", 0) or 0),
            iet=int(data.get("iet", 0) or 0),
            oet=int(data.get("oet", 0) or 0),
            mod=int(data.get("mod", 0) or 0),
            enb=int(data.get("enb", 0) or 0),
        )

    @property
    def import_power_w(self) -> int:
        return max(0, self.pac)

    @property
    def export_power_w(self) -> int:
        return abs(min(0, self.pac))

    @property
    def import_today_kwh(self) -> float:
        return self.itd / 100.0

    @property
    def export_today_kwh(self) -> float:
        return self.otd / 100.0

    @property
    def import_total_kwh(self) -> float:
        return self.iet / 10.0

    @property
    def export_total_kwh(self) -> float:
        return self.oet / 10.0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "import_power_w": self.import_power_w,
                "export_power_w": self.export_power_w,
                "import_today_kwh": round(self.import_today_kwh, 2),
                "export_today_kwh": round(self.export_today_kwh, 2),
                "import_total_kwh": round(self.import_total_kwh, 1),
                "export_total_kwh": round(self.export_total_kwh, 1),
            }
        )
        return data


@dataclass(slots=True)
class BatteryData:
    flg: int = 0
    tim: str = ""
    ppv: int = 0
    etdpv: int = 0
    etopv: int = 0
    cst: int = 0
    bst: int = 0
    eb1: int = 0
    wb1: int = 0
    vb: int = 0
    cb: int = 0
    pb: int = 0
    tb: int = 0
    soc: int = 0
    soh: int = 0
    cli: int = 0
    clo: int = 0
    ebi: int = 0
    ebo: int = 0
    eaci: int = 0
    eaco: int = 0
    vesp: int = 0
    cesp: int = 0
    fesp: int = 0
    pescp: int = 0
    rpesp: int = 0
    etdesp: int = 0
    etoesp: int = 0
    charge_ac_td: int = 0
    charge_ac_to: int = 0

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "BatteryData":
        return cls(
            flg=int(data.get("flg", 0) or 0),
            tim=str(data.get("tim", "")).strip(),
            ppv=int(data.get("ppv", 0) or 0),
            etdpv=int(data.get("etdpv", 0) or 0),
            etopv=int(data.get("etopv", 0) or 0),
            cst=int(data.get("cst", 0) or 0),
            bst=int(data.get("bst", 0) or 0),
            eb1=int(data.get("eb1", 0) or 0),
            wb1=int(data.get("wb1", 0) or 0),
            vb=int(data.get("vb", 0) or 0),
            cb=int(data.get("cb", 0) or 0),
            pb=int(data.get("pb", 0) or 0),
            tb=int(data.get("tb", 0) or 0),
            soc=int(data.get("soc", 0) or 0),
            soh=int(data.get("soh", 0) or 0),
            cli=int(data.get("cli", 0) or 0),
            clo=int(data.get("clo", 0) or 0),
            ebi=int(data.get("ebi", 0) or 0),
            ebo=int(data.get("ebo", 0) or 0),
            eaci=int(data.get("eaci", 0) or 0),
            eaco=int(data.get("eaco", 0) or 0),
            vesp=int(data.get("vesp", 0) or 0),
            cesp=int(data.get("cesp", 0) or 0),
            fesp=int(data.get("fesp", 0) or 0),
            pescp=int(data.get("pesp", 0) or 0),
            rpesp=int(data.get("rpesp", 0) or 0),
            etdesp=int(data.get("etdesp", 0) or 0),
            etoesp=int(data.get("etoesp", 0) or 0),
            charge_ac_td=int(data.get("charge_ac_td", 0) or 0),
            charge_ac_to=int(data.get("charge_ac_to", 0) or 0),
        )

    @property
    def voltage_v(self) -> float:
        return self.vb / 10.0

    @property
    def current_a(self) -> float:
        return self.cb / 10.0

    @property
    def temperature_c(self) -> float:
        return self.tb / 10.0

    @property
    def charge_power_w(self) -> int:
        return abs(min(0, self.pb))

    @property
    def discharge_power_w(self) -> int:
        return max(0, self.pb)

    @property
    def energy_in_kwh(self) -> float:
        return self.ebi / 10.0

    @property
    def energy_out_kwh(self) -> float:
        return self.ebo / 10.0

    @property
    def charge_ac_total_kwh(self) -> float:
        return self.charge_ac_to / 10.0

    @property
    def communication_status_name(self) -> str:
        return BATTERY_COMMUNICATION_STATUS.get(self.cst, f"Desconocido ({self.cst})")

    @property
    def battery_status_name(self) -> str:
        return BATTERY_STATUS.get(self.bst, f"Desconocido ({self.bst})")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "voltage_v": round(self.voltage_v, 1),
                "current_a": round(self.current_a, 1),
                "temperature_c": round(self.temperature_c, 1),
                "charge_power_w": self.charge_power_w,
                "discharge_power_w": self.discharge_power_w,
                "energy_in_kwh": round(self.energy_in_kwh, 1),
                "energy_out_kwh": round(self.energy_out_kwh, 1),
                "charge_ac_total_kwh": round(self.charge_ac_total_kwh, 1),
                "communication_status_name": self.communication_status_name,
                "battery_status_name": self.battery_status_name,
            }
        )
        return data


# ============================================================
# MODELOS DE SCHEDULE
# ============================================================

@dataclass(slots=True)
class ScheduleSlot:
    start_hour: int
    start_minute: int
    duration: int
    mode: str = "charge"

    @classmethod
    def from_raw(cls, code: int) -> Optional["ScheduleSlot"]:
        decoded = decode_schedule_word(int(code or 0))
        if not decoded["enabled"]:
            return None
        return cls(
            start_hour=int(decoded["start_hour"]),
            start_minute=int(decoded["start_minute"]),
            duration=int(decoded["duration"]),
            mode=str(decoded["mode"]),
        )

    @classmethod
    def from_time(cls, start: str, duration: int, mode: str) -> "ScheduleSlot":
        hour, minute = map(int, start.split(":"))
        return cls(
            start_hour=hour,
            start_minute=minute,
            duration=int(duration),
            mode=str(mode).strip().lower(),
        )

    @property
    def end_hour(self) -> int:
        return (self.start_hour + self.duration) % 24

    @property
    def end_minute(self) -> int:
        return self.start_minute

    @property
    def start_text(self) -> str:
        return f"{self.start_hour:02d}:{self.start_minute:02d}"

    @property
    def end_text(self) -> str:
        return f"{self.end_hour:02d}:{self.end_minute:02d}"

    @property
    def time_range(self) -> str:
        return f"{self.start_text}-{self.end_text}"

    def human_readable(self, format: str = "{start} - {end} ({mode})") -> str:
        return format.format(
            start=self.start_text,
            end=self.end_text,
            mode=self.mode,
        )

    def validate(self) -> None:
        if not (0 <= int(self.start_hour) <= 23):
            raise ValueError("Hour must be between 0 and 23")
        if int(self.start_minute) not in (0, 30):
            raise ValueError("Minutes must be 0 or 30")
        if not (1 <= int(self.duration) <= 4):
            raise ValueError("Duration must be between 1 and 4 hours")
        if self.mode not in {"charge", "discharge"}:
            raise ValueError("mode must be 'charge' or 'discharge'")

        end_hour_absolute = self.start_hour + self.duration
        if end_hour_absolute > 24:
            raise ValueError(
                f"Slot ending at {end_hour_absolute}:00 crosses midnight. "
                f"At {self.start_hour}:00 max duration is {24 - self.start_hour} hours"
            )

    def to_raw(self) -> int:
        self.validate()
        return encode_schedule_word(
            enabled=True,
            start_hour=self.start_hour,
            start_minute=self.start_minute,
            duration=self.duration,
            mode=self.mode,
        )

    @staticmethod
    def validate_slots(slots: List["ScheduleSlot"]) -> None:
        if len(slots) > 6:
            raise ValueError("Maximum 6 slots per day allowed")

        sorted_slots = sorted(slots, key=lambda x: (x.start_hour, x.start_minute))

        for i, slot in enumerate(sorted_slots):
            slot.validate()

            if i < len(sorted_slots) - 1:
                next_slot = sorted_slots[i + 1]
                current_end_hour = slot.start_hour + slot.duration
                current_end_min = slot.start_minute

                if (
                    current_end_hour > next_slot.start_hour
                    or (
                        current_end_hour == next_slot.start_hour
                        and current_end_min > next_slot.start_minute
                    )
                ):
                    raise ValueError(
                        f"Slot {slot.human_readable()} overlaps with {next_slot.human_readable()}"
                    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_hour": self.start_hour,
            "start_minute": self.start_minute,
            "duration": self.duration,
            "mode": self.mode,
            "end_hour": self.end_hour,
            "end_minute": self.end_minute,
            "start_text": self.start_text,
            "end_text": self.end_text,
            "time_range": self.time_range,
            "human": self.human_readable(),
            "raw": self.to_raw(),
        }


class BatterySchedule:
    DAYS = ["Mon", "Tus", "Wen", "Thu", "Fri", "Sat", "Sun"]

    @staticmethod
    def decode_schedule(raw_schedule: Dict[str, Any]) -> Dict[str, List[ScheduleSlot]]:
        return {
            day: [
                slot
                for code in _safe_list(raw_schedule.get(day))[:6]
                if (slot := ScheduleSlot.from_raw(int(code or 0))) is not None
            ]
            for day in BatterySchedule.DAYS
        }

    @staticmethod
    def encode_schedule(
        slots: Dict[str, List[ScheduleSlot]],
        pin: int = 5000,
        pout: int = 5000,
    ) -> Dict[str, Any]:
        for day_slots in slots.values():
            if day_slots:
                ScheduleSlot.validate_slots(day_slots)

        payload: Dict[str, Any] = {"Pin": int(pin), "Pout": int(pout)}
        for day in BatterySchedule.DAYS:
            day_slots = list(slots.get(day, []))
            raw_values = [slot.to_raw() for slot in day_slots]
            while len(raw_values) < 6:
                raw_values.append(0)
            payload[day] = raw_values[:6]
        return payload


@dataclass(slots=True)
class DailySchedule:
    day_key: str
    slots: List[ScheduleSlot] = field(default_factory=list)

    @property
    def day_name(self) -> str:
        return DAY_NAME_MAP.get(self.day_key, self.day_key)

    @classmethod
    def from_raw_list(cls, day_key: str, raw_values: List[int]) -> "DailySchedule":
        slots: List[ScheduleSlot] = []
        for raw in raw_values[:6]:
            slot = ScheduleSlot.from_raw(int(raw or 0))
            if slot is not None:
                slots.append(slot)
        return cls(day_key=day_key, slots=slots)

    def raw_values(self) -> List[int]:
        values = [slot.to_raw() for slot in self.slots]
        while len(values) < 6:
            values.append(0)
        return values[:6]

    def summary(self) -> List[str]:
        return [slot.human_readable() for slot in self.slots]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day_key": self.day_key,
            "day_name": self.day_name,
            "slots": [slot.to_dict() for slot in self.slots],
            "raw_values": self.raw_values(),
            "summary": self.summary(),
        }


@dataclass(slots=True)
class ScheduleConfig:
    pin: int = 0
    pout: int = 0
    days: Dict[str, DailySchedule] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "ScheduleConfig":
        days: Dict[str, DailySchedule] = {}
        for day_key in DAY_KEYS:
            raw_values = list(_safe_list(data.get(day_key)))
            days[day_key] = DailySchedule.from_raw_list(day_key, raw_values)
        return cls(
            pin=int(data.get("Pin", 0) or 0),
            pout=int(data.get("Pout", 0) or 0),
            days=days,
        )

    def get_day(self, day_key: str) -> Optional[DailySchedule]:
        return self.days.get(day_key)

    def set_day_slots(self, day_key: str, slots: List[ScheduleSlot]) -> None:
        ScheduleSlot.validate_slots(slots)
        self.days[day_key] = DailySchedule(day_key=day_key, slots=list(slots))

    def summary(self) -> Dict[str, List[str]]:
        return {
            day: (self.days[day].summary() if day in self.days else [])
            for day in DAY_KEYS_HUMAN
        }

    def to_api_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"Pin": int(self.pin), "Pout": int(self.pout)}
        for day_key in DAY_KEYS:
            daily = self.days.get(day_key)
            payload[day_key] = daily.raw_values() if daily else [0, 0, 0, 0, 0, 0]
        return payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Pin": self.pin,
            "Pout": self.pout,
            "days": {k: v.to_dict() for k, v in self.days.items()},
            "summary": self.summary(),
            "raw": self.to_api_payload(),
        }


# ============================================================
# MODELOS DE ESTADO AGREGADO / FLUJOS
# ============================================================

@dataclass(slots=True)
class EnergyFlow:
    solar_w: int = 0
    grid_w: int = 0
    import_grid_w: int = 0
    export_grid_w: int = 0
    battery_power_w: int = 0
    battery_charge_w: int = 0
    battery_discharge_w: int = 0
    home_consumption_w: int = 0

    @classmethod
    def build(cls, solar_w: int, grid_w: int, battery_power_w: int) -> "EnergyFlow":
        import_grid_w = max(0, int(grid_w))
        export_grid_w = abs(min(0, int(grid_w)))
        battery_discharge_w = max(0, int(battery_power_w))
        battery_charge_w = abs(min(0, int(battery_power_w)))

        home_consumption_w = max(
            0,
            int(solar_w) + import_grid_w + battery_discharge_w - battery_charge_w - export_grid_w,
        )

        return cls(
            solar_w=int(solar_w),
            grid_w=int(grid_w),
            import_grid_w=import_grid_w,
            export_grid_w=export_grid_w,
            battery_power_w=int(battery_power_w),
            battery_charge_w=battery_charge_w,
            battery_discharge_w=battery_discharge_w,
            home_consumption_w=home_consumption_w,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SystemSnapshot:
    timestamp: str = field(default_factory=_now_str)
    inverter_info: Optional[InverterInfo] = None
    inverter_data: Optional[InverterData] = None
    meter_info: Optional[MeterInfo] = None
    meter_data: Optional[MeterData] = None
    battery_config: Optional[BatteryConfig] = None
    battery_data: Optional[BatteryData] = None
    schedule: Optional[ScheduleConfig] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "inverter_info": self.inverter_info.to_dict() if self.inverter_info else None,
            "inverter_data": self.inverter_data.to_dict() if self.inverter_data else None,
            "meter_info": self.meter_info.to_dict() if self.meter_info else None,
            "meter_data": self.meter_data.to_dict() if self.meter_data else None,
            "battery_config": self.battery_config.to_dict() if self.battery_config else None,
            "battery_data": self.battery_data.to_dict() if self.battery_data else None,
            "schedule": self.schedule.to_dict() if self.schedule else None,
        }


@dataclass(slots=True)
class SystemState:
    timestamp: str = field(default_factory=_now_str)

    solar: int = 0
    solar_today: float = 0.0
    solar_total: float = 0.0
    pv1_power: Optional[int] = None
    pv2_power: Optional[int] = None
    pv1_voltage: Optional[float] = None
    pv2_voltage: Optional[float] = None
    pv1_current: Optional[float] = None
    pv2_current: Optional[float] = None

    grid: int = 0
    import_grid: int = 0
    export_grid: int = 0
    import_today: float = 0.0
    export_today: float = 0.0
    import_total: float = 0.0
    export_total: float = 0.0

    soc: int = 0
    soh: int = 0
    battery_power: int = 0
    battery_charge: int = 0
    battery_discharge: int = 0
    battery_voltage: float = 0.0
    battery_current: float = 0.0
    battery_temp: float = 0.0
    battery_state: int = 0
    battery_state_name: str = ""
    battery_comm_status: int = 0
    battery_comm_status_name: str = ""
    battery_energy_in: float = 0.0
    battery_energy_out: float = 0.0
    battery_charge_total: float = 0.0

    consumo: float = 0.0
    autosuf: float = 0.0
    autoconsumo: float = 0.0

    mode: int = 0
    mode_name: str = ""
    charge_max: int = 100
    discharge_max: int = 10

    inverter_status: int = 0
    inverter_status_name: str = ""
    inverter_error: int = 0
    inverter_error_name: str = ""
    inverter_warning: int = 0
    inverter_rate: int = 0
    inverter_safety: int = 0
    inverter_temp: float = 0.0
    inverter_frequency: float = 0.0
    inverter_pf: float = 0.0
    inverter_ac_voltage: float = 0.0
    inverter_ac_current: float = 0.0
    inverter_hours_total: int = 0

    schedule_pin: int = 0
    schedule_pout: int = 0
    schedule_summary: Dict[str, List[str]] = field(default_factory=dict)

    has_meter: bool = False
    has_battery: bool = False
    inverter_sn: str = ""
    battery_sn: str = ""

    @classmethod
    def from_snapshot(cls, snapshot: SystemSnapshot) -> "SystemState":
        inverter_info = snapshot.inverter_info
        inverter_data = snapshot.inverter_data
        meter_info = snapshot.meter_info
        meter_data = snapshot.meter_data
        battery_config = snapshot.battery_config
        battery_data = snapshot.battery_data
        schedule = snapshot.schedule

        # Producción solar real calculada desde los strings FV.
        # En este sistema inverter_data.pac NO es la producción solar total.
        if inverter_data is not None:
            solar_w = int(inverter_data.total_pv_power_w or 0)
        else:
            solar_w = 0

        # Flujo real de red desde getdev.cgi?device=3.
        # meter_data (getdevdata) es el dato fresco de cada ciclo.
        # meter_info (getdev) se cachea al arrancar, usarlo solo como fallback.
        if meter_data is not None:
            grid_w = int(meter_data.pac or 0)
        elif meter_info is not None:
            grid_w = int(meter_info.meter_pac or 0)
        else:
            grid_w = 0

        battery_power_w = battery_data.pb if battery_data else 0

        flow = EnergyFlow.build(
            solar_w=solar_w,
            grid_w=grid_w,
            battery_power_w=battery_power_w,
        )

        # Consumo real calculado por balance:
        # solar + importación red + descarga batería - carga batería - exportación
        consumo = float(flow.home_consumption_w)

        autosuf = 0.0
        if consumo > 0:
            energia_propia = flow.solar_w + flow.battery_discharge_w - flow.battery_charge_w
            autosuf = max(0.0, min(100.0, (energia_propia * 100.0) / consumo))

        autoconsumo = 0.0
        if flow.solar_w > 0:
            solar_utilizada = max(0, flow.solar_w - flow.export_grid_w)
            autoconsumo = max(0.0, min(100.0, (solar_utilizada * 100.0) / flow.solar_w))

        return cls(
            timestamp=snapshot.timestamp,

            solar=flow.solar_w,
            solar_today=(inverter_data.etd / 10.0) if inverter_data else 0.0,
            solar_total=(inverter_data.eto / 10.0) if inverter_data else 0.0,
            pv1_power=inverter_data.pv1_power_w if inverter_data else None,
            pv2_power=inverter_data.pv2_power_w if inverter_data else None,
            pv1_voltage=inverter_data.pv1_voltage_v if inverter_data else None,
            pv2_voltage=inverter_data.pv2_voltage_v if inverter_data else None,
            pv1_current=inverter_data.pv1_current_a if inverter_data else None,
            pv2_current=inverter_data.pv2_current_a if inverter_data else None,

            grid=grid_w,
            import_grid=flow.import_grid_w,
            export_grid=flow.export_grid_w,
            import_today=meter_data.import_today_kwh if meter_data else 0.0,
            export_today=meter_data.export_today_kwh if meter_data else 0.0,
            import_total=meter_data.import_total_kwh if meter_data else 0.0,
            export_total=meter_data.export_total_kwh if meter_data else 0.0,

            soc=battery_data.soc if battery_data else 0,
            soh=battery_data.soh if battery_data else 0,
            battery_power=battery_power_w,
            battery_charge=flow.battery_charge_w,
            battery_discharge=flow.battery_discharge_w,
            battery_voltage=battery_data.voltage_v if battery_data else 0.0,
            battery_current=battery_data.current_a if battery_data else 0.0,
            battery_temp=battery_data.temperature_c if battery_data else 0.0,
            battery_state=battery_data.bst if battery_data else 0,
            battery_state_name=battery_data.battery_status_name if battery_data else "",
            battery_comm_status=battery_data.cst if battery_data else 0,
            battery_comm_status_name=battery_data.communication_status_name if battery_data else "",
            battery_energy_in=battery_data.energy_in_kwh if battery_data else 0.0,
            battery_energy_out=battery_data.energy_out_kwh if battery_data else 0.0,
            battery_charge_total=battery_data.charge_ac_total_kwh if battery_data else 0.0,

            consumo=consumo,
            autosuf=autosuf,
            autoconsumo=autoconsumo,

            mode=battery_config.mod_r if battery_config else 0,
            mode_name=battery_config.mode_name if battery_config else "",
            charge_max=battery_config.charge_max if battery_config else 100,
            discharge_max=battery_config.discharge_max if battery_config else 10,

            inverter_status=inverter_data.stu if inverter_data else 0,
            inverter_status_name=inverter_data.status_name if inverter_data else "",
            inverter_error=inverter_data.err if inverter_data else 0,
            inverter_error_name=inverter_data.error_name if inverter_data else "",
            inverter_warning=inverter_data.wan if inverter_data else 0,
            inverter_rate=inverter_info.rate if inverter_info else 0,
            inverter_safety=inverter_info.safety if inverter_info else 0,
            inverter_temp=inverter_data.temperature_c if inverter_data else 0.0,
            inverter_frequency=inverter_data.frequency_hz if inverter_data else 0.0,
            inverter_pf=inverter_data.power_factor if inverter_data else 0.0,
            inverter_ac_voltage=(inverter_data.ac_voltage_v or 0.0) if inverter_data else 0.0,
            inverter_ac_current=(inverter_data.ac_current_a or 0.0) if inverter_data else 0.0,
            inverter_hours_total=inverter_data.hto if inverter_data else 0,

            schedule_pin=schedule.pin if schedule else 0,
            schedule_pout=schedule.pout if schedule else 0,
            schedule_summary=schedule.summary() if schedule else {day: [] for day in DAY_KEYS_HUMAN},

            has_meter=meter_info is not None or meter_data is not None,
            has_battery=battery_config is not None or battery_data is not None,
            inverter_sn=inverter_info.isn if inverter_info else "",
            battery_sn=(
                str(battery_config.sn) if battery_config and battery_config.sn
                else (inverter_info.isn if inverter_info else "")
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,

            "solar": self.solar,
            "solar_today": round(self.solar_today, 2),
            "solar_total": round(self.solar_total, 2),
            "pv1_power": self.pv1_power,
            "pv2_power": self.pv2_power,
            "pv1_voltage": _round_or_none(self.pv1_voltage, 1),
            "pv2_voltage": _round_or_none(self.pv2_voltage, 1),
            "pv1_current": _round_or_none(self.pv1_current, 1),
            "pv2_current": _round_or_none(self.pv2_current, 1),

            "grid": self.grid,
            "import_grid": self.import_grid,
            "export_grid": self.export_grid,
            "import_today": round(self.import_today, 2),
            "export_today": round(self.export_today, 2),
            "import_total": round(self.import_total, 1),
            "export_total": round(self.export_total, 1),

            "soc": self.soc,
            "soh": self.soh,
            "battery_power": self.battery_power,
            "battery_charge": self.battery_charge,
            "battery_discharge": self.battery_discharge,
            "battery_voltage": round(self.battery_voltage, 1),
            "battery_current": round(self.battery_current, 1),
            "battery_temp": round(self.battery_temp, 1),
            "battery_state": self.battery_state,
            "battery_state_name": self.battery_state_name,
            "battery_comm_status": self.battery_comm_status,
            "battery_comm_status_name": self.battery_comm_status_name,
            "battery_energy_in": round(self.battery_energy_in, 1),
            "battery_energy_out": round(self.battery_energy_out, 1),
            "battery_charge_total": round(self.battery_charge_total, 1),

            "consumo": round(self.consumo, 2),
            "autosuf": round(self.autosuf, 1),
            "autoconsumo": round(self.autoconsumo, 1),

            "mode": self.mode,
            "mode_name": self.mode_name,
            "charge_max": self.charge_max,
            "discharge_max": self.discharge_max,

            "inverter_status": self.inverter_status,
            "inverter_status_name": self.inverter_status_name,
            "inverter_error": self.inverter_error,
            "inverter_error_name": self.inverter_error_name,
            "inverter_warning": self.inverter_warning,
            "inverter_rate": self.inverter_rate,
            "inverter_safety": self.inverter_safety,
            "inverter_temp": round(self.inverter_temp, 1),
            "inverter_frequency": round(self.inverter_frequency, 2),
            "inverter_pf": round(self.inverter_pf, 2),
            "inverter_ac_voltage": round(self.inverter_ac_voltage, 1),
            "inverter_ac_current": round(self.inverter_ac_current, 1),
            "inverter_hours_total": self.inverter_hours_total,

            "schedule_pin": self.schedule_pin,
            "schedule_pout": self.schedule_pout,
            "schedule_summary": self.schedule_summary,

            "has_meter": self.has_meter,
            "has_battery": self.has_battery,
            "inverter_sn": self.inverter_sn,
            "battery_sn": self.battery_sn,
        }


__all__ = [
    "BATTERY_MODES",
    "BATTERY_COMMUNICATION_STATUS",
    "BATTERY_STATUS",
    "INVERTER_STATUS",
    "INVERTER_ERRORS",
    "DAY_KEYS",
    "DAY_KEYS_HUMAN",
    "DAY_NAME_MAP",
    "DAY_KEY_FROM_SPANISH",
    "decode_schedule_word",
    "encode_schedule_word",
    "DongleInfo",
    "InverterInfo",
    "MeterInfo",
    "BatteryConfig",
    "DeviceDiscovery",
    "InverterData",
    "MeterData",
    "BatteryData",
    "ScheduleSlot",
    "BatterySchedule",
    "DailySchedule",
    "ScheduleConfig",
    "EnergyFlow",
    "SystemSnapshot",
    "SystemState",
]
