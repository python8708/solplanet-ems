-- Schema para solplanet-ems
-- MySQL / MariaDB

CREATE DATABASE IF NOT EXISTS solplanet_ems
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE solplanet_ems;

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
);

INSERT IGNORE INTO energy_live (id) VALUES (1);

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
);

CREATE TABLE IF NOT EXISTS energy_daily (
    day DATE PRIMARY KEY,
    import_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    export_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    solar_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    consumo_kwh DECIMAL(12,2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
