#!/usr/bin/env python3
"""
Experimental Modbus-like parser for UPS/Inverter protocol
Based on register-based protocol parsing approach
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

# ============================================================================
# Error code constants (placeholder - needs actual error codes)
# ============================================================================

INVERTER_ERROR = [None] * 128  # 8 registers * 16 bits
INVERTER_WARNING = [None] * 128
CHARGER_ERROR = [None] * 128
CHARGER_WARNING = [None] * 128

# TODO: Fill in actual error codes from UPS documentation
# Example:
# INVERTER_ERROR[0] = "Overvoltage"
# INVERTER_ERROR[1] = "Undervoltage"
# etc.

# ============================================================================
# Conversion functions
# ============================================================================

def int16(address: int, registers: Dict[int, int]) -> int:
    """Convert signed 16-bit integer from register."""
    if address not in registers:
        return 0
    val = registers[address]
    bits = 16
    if (val & (1 << (bits - 1))) != 0:  # if sign bit is set
        val = val - (1 << bits)  # compute negative value
    return val


def uint16(address: int, registers: Dict[int, int]) -> int:
    """Convert unsigned 16-bit integer from register."""
    if address not in registers:
        return 0
    return registers[address]


def version(address: int, registers: Dict[int, int]) -> str:
    """Convert version number from register."""
    if address not in registers:
        return "0.0.0"
    val = registers[address]
    return f"{val // 10000}.{(val // 100) % 100}.{val % 100}"


def accumulated_kwh(address: int, registers: Dict[int, int]) -> float:
    """Convert accumulated kWh from two registers."""
    if address not in registers or address + 1 not in registers:
        return 0.0
    return registers[address] * 1000 + registers[address + 1] * 0.1


def time_seconds(address: int, registers: Dict[int, int]) -> int:
    """Convert time from three registers (hours, minutes, seconds)."""
    if address not in registers or address + 1 not in registers or address + 2 not in registers:
        return 0
    return int(registers[address]) * 60 * 60 + int(registers[address + 1]) * 60 + int(registers[address + 2])


def serial_number(address: int, registers: Dict[int, int]) -> int:
    """Convert serial number from two registers."""
    if address not in registers or address + 1 not in registers:
        return 0
    return registers[address] << 16 | registers[address + 1]


def model(address: int, registers: Dict[int, int]) -> str:
    """Convert model string from registers."""
    if address not in registers or address + 1 not in registers:
        return ""
    a = chr(registers[address] >> 8 & 0xFF)
    b = chr(registers[address] & 0xFF)
    return f"{a}{b}{registers[address + 1]}"


def error_bits(address: int, registers: Dict[int, int], error_codes: List[Optional[str]]) -> str:
    """Parse error bits from registers."""
    if address not in registers:
        return "No errors"
    
    number_of_registers = len(error_codes) // 16
    errors_found = []

    for i in range(number_of_registers):
        reg_addr = address + i
        if reg_addr not in registers:
            continue
        for j in range(16):
            if registers[reg_addr] & (1 << j):
                error_index = i * 16 + j
                if error_index < len(error_codes) and error_codes[error_index]:
                    _LOGGER.debug("Error code %s found: %s", error_index, error_codes[error_index])
                    errors_found.append(error_codes[error_index])
                else:
                    errors_found.append(f"Unknown error bit {error_index}")

    if len(errors_found) == 0:
        return "No errors"

    _LOGGER.debug("Errors found: %s", errors_found)
    return ", ".join(errors_found)


# ============================================================================
# Data conversion functions
# ============================================================================

def convert_registers_to_dict(data: bytes, start_address: int = 0) -> Dict[int, int]:
    """
    Convert raw bytes to register dictionary.
    Assumes big-endian 16-bit registers.
    """
    registers = {}
    if len(data) < 2:
        return registers
    
    # Skip header if present (first 5 bytes)
    offset = 5 if len(data) > 5 else 0
    payload = data[offset:]
    
    for i in range(0, len(payload) - 1, 2):
        register_address = start_address + (i // 2)
        value = int.from_bytes(payload[i:i+2], byteorder='big', signed=False)
        registers[register_address] = value
    
    return registers


def convert_partArr6(registers: Dict[int, int]) -> Dict[str, Any]:
    """
    Convert partArr6 registers (main inverter data).
    Addresses starting from 25201.
    """
    if not registers:
        return {}
    
    result = {}
    try:
        result["WorkState"] = int16(25201, registers)
        result["AcVoltageGrade"] = int16(25202, registers)
        result["RatedPower"] = int16(25203, registers)
        result["InverterBatteryVoltage"] = int16(25205, registers) / 10.0  # Divide by 10 for voltage
        result["InverterVoltage"] = int16(25206, registers) / 10.0
        result["GridVoltage"] = int16(25207, registers) / 10.0  # Input voltage
        result["BusVoltage"] = int16(25208, registers) / 10.0
        result["ControlCurrent"] = int16(25209, registers) / 10.0
        result["InverterCurrent"] = int16(25210, registers) / 10.0
        result["GridCurrent"] = int16(25211, registers) / 10.0
        result["LoadCurrent"] = int16(25212, registers) / 10.0
        result["PInverter"] = int16(25213, registers)
        result["PGrid"] = int16(25214, registers)
        result["PLoad"] = int16(25215, registers)  # Load power
        result["LoadPercent"] = int16(25216, registers)
        result["SInverter"] = int16(25217, registers)
        result["SGrid"] = int16(25218, registers)
        result["Sload"] = int16(25219, registers)
        result["Qinverter"] = int16(25221, registers)
        result["Qgrid"] = int16(25222, registers)
        result["Qload"] = int16(25223, registers)
        result["InverterFrequency"] = int16(25225, registers) / 10.0  # Divide by 10 for frequency
        result["GridFrequency"] = int16(25226, registers) / 10.0
        result["InverterMaxNumber"] = uint16(25229, registers)
        result["CombineType"] = uint16(25230, registers)
        result["InverterNumber"] = uint16(25231, registers)
        result["AcRadiatorTemperature"] = int16(25233, registers)
        result["TransformerTemperature"] = int16(25234, registers)
        result["DcRadiatorTemperature"] = int16(25235, registers)
        result["InverterRelayState"] = int16(25237, registers)
        result["GridRelayState"] = int16(25238, registers)
        result["LoadRelayState"] = int16(25239, registers)
        result["N_LineRelayState"] = int16(25240, registers)
        result["DCRelayState"] = int16(25241, registers)
        result["EarthRelayState"] = int16(25242, registers)
        result["AccumulatedChargerPower"] = accumulated_kwh(25245, registers)
        result["AccumulatedDischargerPower"] = accumulated_kwh(25247, registers)
        result["AccumulatedBuyPower"] = accumulated_kwh(25249, registers)
        result["AccumulatedSellPower"] = accumulated_kwh(25251, registers)
        result["AccumulatedLoadPower"] = accumulated_kwh(25253, registers)
        result["AccumulatedSelfUsePower"] = accumulated_kwh(25255, registers)
        result["AccumulatedPvSellPower"] = accumulated_kwh(25257, registers)
        result["AccumulatedGridChargerPower"] = accumulated_kwh(25259, registers)
        result["InverterErrorMessage"] = error_bits(25261, registers, INVERTER_ERROR)
        result["InverterWarningMessage"] = error_bits(25265, registers, INVERTER_WARNING)
        result["BattPower"] = int16(25273, registers)
        result["BattCurrent"] = int16(25274, registers) / 10.0
        result["RatedPowerW"] = int16(25277, registers)
    except Exception as e:
        _LOGGER.error(f"Error converting partArr6: {e}")
    
    return result


def convert_partArr3(registers: Dict[int, int]) -> Dict[str, Any]:
    """
    Convert partArr3 registers (charger data).
    Addresses starting from 15201.
    """
    if not registers:
        return {}
    
    result = {}
    try:
        result["ChargerWorkstate"] = int16(15201, registers)
        result["MpptState"] = int16(15202, registers)
        result["ChargingState"] = int16(15203, registers)
        result["PvVoltage"] = int16(15205, registers) / 10.0
        result["BatteryVoltage"] = int16(15206, registers) / 10.0
        result["ChargerCurrent"] = int16(15207, registers) / 10.0
        result["ChargerPower"] = int16(15208, registers)
        result["RadiatorTemperature"] = int16(15209, registers)
        result["ExternalTemperature"] = int16(15210, registers)
        result["BatteryRelay"] = int16(15211, registers)
        result["PvRelay"] = int16(15212, registers)
        result["ChargerErrorMessage"] = error_bits(15213, registers, CHARGER_ERROR)
        result["ChargerWarningMessage"] = error_bits(15214, registers, CHARGER_WARNING)
        result["BattVolGrade"] = int16(15215, registers)
        result["RatedCurrent"] = int16(15216, registers)
        result["AccumulatedPower"] = accumulated_kwh(15217, registers)
        result["AccumulatedTime"] = time_seconds(15219, registers)
    except Exception as e:
        _LOGGER.error(f"Error converting partArr3: {e}")
    
    return result


def convert_battery_status(registers: Dict[int, int]) -> Dict[str, Any]:
    """Convert battery status registers (PV1900 compatible)."""
    result = {}
    try:
        if 113 in registers:
            result["StateOfCharge"] = registers[113]  # Battery level %
        if 114 in registers:
            result["BatteryStateOfHealth"] = registers[114]
    except Exception as e:
        _LOGGER.debug(f"Battery status not available: {e}")
    return result


# ============================================================================
# Main parser function
# ============================================================================

@dataclass
class UPSTelemetryModbus:
    """Extended telemetry structure with Modbus parsing"""
    # Basic values (matching current structure)
    input_voltage: float = 0.0
    output_voltage: float = 0.0
    battery_voltage: float = 0.0
    battery_level: int = 0
    load_percent: int = 0
    load_power: int = 0
    frequency: float = 0.0
    input_frequency: float = 0.0
    temperature: float = 0.0
    timestamp: str = ""
    status: str = "unknown"
    uptime: str = ""
    
    # Extended values from Modbus parsing
    grid_voltage: float = 0.0
    bus_voltage: float = 0.0
    inverter_current: float = 0.0
    grid_current: float = 0.0
    load_current: float = 0.0
    inverter_power: int = 0
    grid_power: int = 0
    work_state: int = 0
    error_message: str = ""
    warning_message: str = ""


def parse_telemetry_modbus(data: bytes, uptime: str = "") -> UPSTelemetryModbus:
    """
    Parse telemetry using Modbus-like register approach.
    This is an experimental parser that maps registers to known addresses.
    """
    telemetry = UPSTelemetryModbus()
    telemetry.timestamp = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    telemetry.uptime = uptime
    
    if len(data) < 5:
        return telemetry
    
    # Try to parse as partArr6 (main inverter data) - addresses 25201+
    registers_6 = convert_registers_to_dict(data, start_address=25201)
    if registers_6:
        part6 = convert_partArr6(registers_6)
        
        # Map to telemetry structure
        # Note: InverterVoltage is output, GridVoltage is input
        telemetry.output_voltage = part6.get("InverterVoltage", 0.0)  # Output voltage (to load)
        telemetry.input_voltage = part6.get("GridVoltage", 0.0)  # Input voltage (from grid/network)
        telemetry.battery_voltage = part6.get("InverterBatteryVoltage", 0.0)
        telemetry.load_percent = part6.get("LoadPercent", 0)
        telemetry.load_power = part6.get("PLoad", 0)
        telemetry.frequency = part6.get("GridFrequency", 0.0)
        telemetry.input_frequency = part6.get("GridFrequency", 0.0)
        
        # Extended values
        telemetry.grid_voltage = part6.get("GridVoltage", 0.0)
        telemetry.bus_voltage = part6.get("BusVoltage", 0.0)
        telemetry.inverter_current = part6.get("InverterCurrent", 0.0)
        telemetry.grid_current = part6.get("GridCurrent", 0.0)
        telemetry.load_current = part6.get("LoadCurrent", 0.0)
        telemetry.inverter_power = part6.get("PInverter", 0)
        telemetry.grid_power = part6.get("PGrid", 0)
        telemetry.work_state = part6.get("WorkState", 0)
        telemetry.error_message = part6.get("InverterErrorMessage", "")
        telemetry.warning_message = part6.get("InverterWarningMessage", "")
        
        # Temperature - try different sources
        telemetry.temperature = (
            part6.get("AcRadiatorTemperature", 0) or
            part6.get("TransformerTemperature", 0) or
            part6.get("DcRadiatorTemperature", 0) or
            0
        )
        
        # Status based on work state or voltage
        if telemetry.input_voltage > 200:
            telemetry.status = "online"
        else:
            telemetry.status = "battery"
    
    # Try to parse as partArr3 (charger data) - addresses 15201+
    registers_3 = convert_registers_to_dict(data, start_address=15201)
    if registers_3:
        part3 = convert_partArr3(registers_3)
        
        # Override battery voltage if available
        if part3.get("BatteryVoltage", 0) > 0:
            telemetry.battery_voltage = part3.get("BatteryVoltage", 0.0)
        
        # Temperature from charger
        if part3.get("RadiatorTemperature", 0) > 0:
            telemetry.temperature = part3.get("RadiatorTemperature", 0)
    
    # Try battery status registers (address 113+)
    registers_batt = convert_registers_to_dict(data, start_address=0)
    if registers_batt:
        battery_status = convert_battery_status(registers_batt)
        if battery_status.get("StateOfCharge", 0) > 0:
            telemetry.battery_level = battery_status.get("StateOfCharge", 0)
    
    return telemetry
