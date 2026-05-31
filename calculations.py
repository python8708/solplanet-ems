"""Cálculos energéticos del sistema EMS Solplanet."""

from __future__ import annotations

from typing import Any, Dict, Optional

from models import (
    BatteryData,
    EnergyFlow,
    InverterData,
    MeterData,
    SystemSnapshot,
    SystemState,
)


def clamp_percentage(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def split_grid_power(grid: int) -> tuple[int, int]:
    grid = int(grid or 0)
    import_grid = max(0, grid)
    export_grid = abs(min(0, grid))
    return import_grid, export_grid


def split_battery_power(battery_power: int) -> tuple[int, int]:
    battery_power = int(battery_power or 0)
    battery_discharge = max(0, battery_power)
    battery_charge = abs(min(0, battery_power))
    return battery_charge, battery_discharge


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    denominator = float(denominator)
    if denominator == 0.0:
        return float(default)
    return float(numerator) / denominator


def calculate_consumption(solar: int, grid: int, battery_power: int) -> float:
    import_grid, export_grid = split_grid_power(grid)
    battery_charge, battery_discharge = split_battery_power(battery_power)

    consumo = (
        int(solar or 0)
        + import_grid
        + battery_discharge
        - battery_charge
        - export_grid
    )

    return float(max(0, consumo))


def calculate_self_sufficiency(
    solar: int,
    battery_discharge: int,
    battery_charge: int,
    consumo: float
) -> float:
    consumo = float(consumo or 0.0)
    if consumo <= 0:
        return 0.0

    energia_propia = (
        int(solar or 0)
        + int(battery_discharge or 0)
        - int(battery_charge or 0)
    )

    autosuf = safe_div(energia_propia * 100.0, consumo, default=0.0)
    return clamp_percentage(autosuf)


def calculate_self_consumption(solar: int, export_grid: int) -> float:
    solar = int(solar or 0)
    export_grid = int(export_grid or 0)

    if solar <= 0:
        return 0.0

    solar_utilizada = max(0, solar - export_grid)
    autoconsumo = safe_div(solar_utilizada * 100.0, solar, default=0.0)
    return clamp_percentage(autoconsumo)


def build_energy_flow(solar: int, grid: int, battery_power: int) -> EnergyFlow:
    return EnergyFlow.build(
        solar_w=int(solar or 0),
        grid_w=int(grid or 0),
        battery_power_w=int(battery_power or 0),
    )


def calculate_home_consumption_from_flow(flow: EnergyFlow) -> int:
    return int(flow.home_consumption_w)


def calculate_solar_used(solar: int, export_grid: int) -> int:
    return max(0, int(solar or 0) - int(export_grid or 0))


def calculate_energy_balance_error(
    solar: int,
    grid: int,
    battery_power: int,
    consumption: int | float,
) -> int:
    import_grid, export_grid = split_grid_power(grid)
    battery_charge, battery_discharge = split_battery_power(battery_power)

    residual = (
        int(solar or 0)
        + import_grid
        + battery_discharge
        - battery_charge
        - export_grid
        - int(round(float(consumption or 0.0)))
    )
    return int(residual)


def calculate_grid_dependency(consumption: int | float, import_grid: int) -> float:
    consumption = float(consumption or 0.0)
    import_grid = float(import_grid or 0.0)
    if consumption <= 0:
        return 0.0
    return clamp_percentage((import_grid * 100.0) / consumption)


def calculate_battery_utilization(
    battery_charge: int,
    battery_discharge: int,
    consumption: int | float,
) -> float:
    consumption = float(consumption or 0.0)
    battery_discharge = float(battery_discharge or 0.0)
    if consumption <= 0:
        return 0.0
    return clamp_percentage((battery_discharge * 100.0) / consumption)


def get_solar_power_from_inverter(
    inverter_data: Optional[InverterData],
    battery_data: Optional[BatteryData] = None,
) -> int:
    """Potencia solar estable.

    Prioridad:
    1. ppv del híbrido/batería
    2. pac AC del inversor como fallback
    """
    if battery_data is not None:
        try:
            ppv = int(battery_data.ppv or 0)
            if ppv >= 0:
                return ppv
        except Exception:
            pass

    if inverter_data is None:
        return 0

    return max(0, int(inverter_data.pac or 0))


def get_grid_power_from_meter(meter_data: Optional[MeterData]) -> int:
    if meter_data is None:
        return 0
    return int(meter_data.pac or 0)


def get_battery_power_from_data(battery_data: Optional[BatteryData]) -> int:
    if battery_data is None:
        return 0
    return int(battery_data.pb or 0)


def build_flow_from_device_data(
    inverter_data: Optional[InverterData],
    meter_data: Optional[MeterData],
    battery_data: Optional[BatteryData],
) -> EnergyFlow:
    solar = get_solar_power_from_inverter(
        inverter_data=inverter_data,
        battery_data=battery_data,
    )
    grid = get_grid_power_from_meter(meter_data)
    battery_power = get_battery_power_from_data(battery_data)
    return build_energy_flow(solar=solar, grid=grid, battery_power=battery_power)


def calculate_metrics(solar: int, grid: int, battery_power: int) -> Dict[str, Any]:
    flow = build_energy_flow(solar=solar, grid=grid, battery_power=battery_power)

    autosuf = calculate_self_sufficiency(
        solar=flow.solar_w,
        battery_discharge=flow.battery_discharge_w,
        battery_charge=flow.battery_charge_w,
        consumo=float(flow.home_consumption_w),
    )

    autoconsumo = calculate_self_consumption(
        solar=flow.solar_w,
        export_grid=flow.export_grid_w,
    )

    dependency = calculate_grid_dependency(
        consumption=flow.home_consumption_w,
        import_grid=flow.import_grid_w,
    )

    battery_util = calculate_battery_utilization(
        battery_charge=flow.battery_charge_w,
        battery_discharge=flow.battery_discharge_w,
        consumption=flow.home_consumption_w,
    )

    return {
        "solar": flow.solar_w,
        "grid": flow.grid_w,
        "import_grid": flow.import_grid_w,
        "export_grid": flow.export_grid_w,
        "battery_power": flow.battery_power_w,
        "battery_charge": flow.battery_charge_w,
        "battery_discharge": flow.battery_discharge_w,
        "consumo": float(flow.home_consumption_w),
        "autosuf": autosuf,
        "autoconsumo": autoconsumo,
        "grid_dependency": dependency,
        "battery_utilization": battery_util,
        "energy_balance_error": calculate_energy_balance_error(
            solar=flow.solar_w,
            grid=flow.grid_w,
            battery_power=flow.battery_power_w,
            consumption=flow.home_consumption_w,
        ),
    }


def calculate_metrics_from_device_data(
    inverter_data: Optional[InverterData],
    meter_data: Optional[MeterData],
    battery_data: Optional[BatteryData],
) -> Dict[str, Any]:
    solar = get_solar_power_from_inverter(
        inverter_data=inverter_data,
        battery_data=battery_data,
    )
    grid = get_grid_power_from_meter(meter_data)
    battery_power = get_battery_power_from_data(battery_data)
    return calculate_metrics(solar=solar, grid=grid, battery_power=battery_power)


def summarize_snapshot(snapshot: SystemSnapshot) -> Dict[str, Any]:
    flow = build_flow_from_device_data(
        inverter_data=snapshot.inverter_data,
        meter_data=snapshot.meter_data,
        battery_data=snapshot.battery_data,
    )

    metrics = calculate_metrics(
        solar=flow.solar_w,
        grid=flow.grid_w,
        battery_power=flow.battery_power_w,
    )

    return {
        "timestamp": snapshot.timestamp,
        "has_meter": snapshot.meter_data is not None,
        "has_battery": snapshot.battery_data is not None,
        "flow": flow.to_dict(),
        "metrics": metrics,
    }


def summarize_state(state: SystemState) -> Dict[str, Any]:
    return {
        "timestamp": state.timestamp,
        "solar": state.solar,
        "grid": state.grid,
        "import_grid": state.import_grid,
        "export_grid": state.export_grid,
        "battery_power": state.battery_power,
        "battery_charge": state.battery_charge,
        "battery_discharge": state.battery_discharge,
        "consumo": round(state.consumo, 2),
        "autosuf": round(state.autosuf, 1),
        "autoconsumo": round(state.autoconsumo, 1),
        "soc": state.soc,
        "soh": state.soh,
        "mode": state.mode,
        "mode_name": state.mode_name,
        "energy_balance_error": calculate_energy_balance_error(
            solar=state.solar,
            grid=state.grid,
            battery_power=state.battery_power,
            consumption=state.consumo,
        ),
    }


def state_to_debug_metrics(state: SystemState) -> Dict[str, Any]:
    summary = summarize_state(state)
    summary.update(
        {
            "grid_dependency": round(
                calculate_grid_dependency(state.consumo, state.import_grid), 1
            ),
            "battery_utilization": round(
                calculate_battery_utilization(
                    state.battery_charge,
                    state.battery_discharge,
                    state.consumo,
                ),
                1,
            ),
        }
    )
    return summary


__all__ = [
    "clamp_percentage",
    "split_grid_power",
    "split_battery_power",
    "safe_div",
    "calculate_consumption",
    "calculate_self_sufficiency",
    "calculate_self_consumption",
    "build_energy_flow",
    "calculate_home_consumption_from_flow",
    "calculate_solar_used",
    "calculate_energy_balance_error",
    "calculate_grid_dependency",
    "calculate_battery_utilization",
    "get_solar_power_from_inverter",
    "get_grid_power_from_meter",
    "get_battery_power_from_data",
    "build_flow_from_device_data",
    "calculate_metrics",
    "calculate_metrics_from_device_data",
    "summarize_snapshot",
    "summarize_state",
    "state_to_debug_metrics",
]
