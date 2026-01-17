#!/usr/bin/env python3
"""
UPS Monitoring Daemon with Web Interface - Fixed Version
"""

import serial
import time
import sys
import struct
import logging
import signal
import threading
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple
from collections import namedtuple
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
import paho.mqtt.client as mqtt
import yaml
import os
import argparse

# Experimental Modbus parser (optional)
try:
    from ups_modbus_parser import parse_telemetry_modbus, UPSTelemetryModbus
    MODBUS_PARSER_AVAILABLE = True
except ImportError:
    MODBUS_PARSER_AVAILABLE = False
    UPSTelemetryModbus = None

# ============================================================================
# Constants
# ============================================================================

# Serial port configuration
SERIAL_BAUDRATE = 9600
SERIAL_TIMEOUT = 2

# UPS wakeup commands
WAKEUP_COMMANDS = [
    "0103271000018f7b",
    "05034e210001c2ac",
    "06034e210001c29f",
    "0a03753000019f72",
]

# UPS protocol commands
UPS_COMMAND_MAIN_PARAMS = "0a037530001b1eb9"
UPS_COMMAND_BATTERY = "0a037918000a5ded"

# Timing constants
WAKEUP_DELAY = 0.3
COMMAND_DELAY = 0.5
POST_WAKEUP_DELAY = 0.5
CONNECTION_RETRY_DELAY = 10
ERROR_RETRY_DELAY = 5

# Telemetry value ranges (raw values from UPS)
VOLTAGE_RANGE = (2200, 2300)  # 220-230V in raw units (divide by 10)
FREQUENCY_RANGE = (490, 510)  # 49-51Hz in raw units (divide by 10)
BATTERY_VOLTAGE_RANGE = (130, 140)  # 13-14V in raw units (divide by 10)
BATTERY_LEVEL_RANGE = (95, 105)  # 95-105%
LOAD_PERCENT_RANGE = (10, 20)  # 10-20%
LOAD_POWER_RANGE = (130, 150)  # 130-150W
TEMPERATURE_RANGE = (30, 40)  # 30-40°C

# Alarm thresholds
MIN_INPUT_VOLTAGE = 180
MIN_BATTERY_LEVEL = 20
MAX_TEMPERATURE = 40
MAX_LOAD_PERCENT = 80

# Status thresholds
ONLINE_VOLTAGE_THRESHOLD = 200

@dataclass
class UPSTelemetry:
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

class UPSWebDaemon:
    def __init__(self, port, web_port=8080, interval=30, 
                 mqtt_broker=None, mqtt_port=1883, mqtt_topic="ups/telemetry",
                 mqtt_username=None, mqtt_password=None,
                 log_level=logging.INFO, log_file="/tmp/ups_web_daemon.log", log_console=True,
                 max_errors=5, use_modbus_parser=False):
        self.port = port
        self.web_port = web_port
        self.interval = interval
        self.ser = None
        self.running = True
        self.connection_errors = 0
        self.max_errors = max_errors
        self.current_telemetry = UPSTelemetry()
        self.start_time = datetime.now()
        self.web_server = None  # Will be set by start_web_server
        
        # MQTT configuration
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.mqtt_topic = mqtt_topic
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.mqtt_client = None
        
        # Prometheus metrics
        self.prom_input_voltage = Gauge('ups_input_voltage', 'Input voltage in volts')
        self.prom_output_voltage = Gauge('ups_output_voltage', 'Output voltage in volts')
        self.prom_battery_voltage = Gauge('ups_battery_voltage', 'Battery voltage in volts')
        self.prom_battery_level = Gauge('ups_battery_level', 'Battery level in percent', ['status'])
        self.prom_load_percent = Gauge('ups_load_percent', 'Load percentage')
        self.prom_load_power = Gauge('ups_load_power', 'Load power in watts')
        self.prom_frequency = Gauge('ups_frequency', 'Frequency in Hz')
        self.prom_input_frequency = Gauge('ups_input_frequency', 'Input frequency in Hz')
        self.prom_temperature = Gauge('ups_temperature', 'Temperature in Celsius')
        self.prom_status = Gauge('ups_status', 'UPS status (1=online, 0=battery)', ['status'])
        
        # Cache for status labels to avoid recreating
        self._status_labels = {}

        # Настройка логирования
        handlers = []
        if log_console:
            handlers.append(logging.StreamHandler(sys.stdout))
        if log_file:
            handlers.append(logging.FileHandler(log_file, mode='a'))
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=handlers,
            force=True
        )
        self.logger = logging.getLogger('UPSWebDaemon')
        
        # Setup Modbus parser (after logger is initialized)
        self.use_modbus_parser = use_modbus_parser and MODBUS_PARSER_AVAILABLE
        
        if use_modbus_parser and not MODBUS_PARSER_AVAILABLE:
            self.logger.warning("⚠️  Modbus parser requested but not available. Using default parser.")
            self.use_modbus_parser = False
        elif use_modbus_parser:
            self.logger.info("✅ Using experimental Modbus parser")

        # Обработчик сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Инициализация MQTT
        if self.mqtt_broker:
            self.init_mqtt()

    def signal_handler(self, signum, frame):
        """Обработчик сигналов для graceful shutdown"""
        self.logger.info(f"Получен сигнал {signum}, завершаем работу...")
        self.running = False
        
        # Stop web server if it exists
        if self.web_server:
            self.logger.info("Остановка веб-сервера...")
            try:
                self.web_server.shutdown()
            except Exception as e:
                self.logger.error(f"Ошибка при остановке веб-сервера: {e}")

    def get_uptime(self):
        """Получение времени работы демона"""
        uptime = datetime.now() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def connect(self):
        """Подключение к UPS"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=SERIAL_BAUDRATE,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=SERIAL_TIMEOUT
            )
            self.ser.dtr = True
            self.ser.rts = False
            time.sleep(1)
            self.ser.flushInput()

            self.logger.info(f"✅ Подключено к {self.port}")
            self.connection_errors = 0
            return True

        except Exception as e:
            self.connection_errors += 1
            self.logger.error(f"❌ Ошибка подключения: {e}")

            if self.connection_errors >= self.max_errors:
                self.logger.error("⚠️  Слишком много ошибок подключения, завершаем работу")
                self.running = False

            return False

    def disconnect(self):
        """Отключение от UPS"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.logger.info("✅ Отключено от UPS")
    
    def init_mqtt(self):
        """Инициализация MQTT клиента"""
        try:
            # Use callback API version 2 to avoid deprecation warning
            try:
                # paho-mqtt 2.0+ uses CallbackAPIVersion
                from paho.mqtt.client import CallbackAPIVersion
                self.mqtt_client = mqtt.Client(
                    callback_api_version=CallbackAPIVersion.VERSION2,
                    client_id="ups_monitor"
                )
            except (ImportError, AttributeError):
                # Fallback for older versions
                self.mqtt_client = mqtt.Client(client_id="ups_monitor")
            
            if self.mqtt_username and self.mqtt_password:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
            
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.mqtt_client.loop_start()
            self.logger.info(f"✅ MQTT клиент подключен к {self.mqtt_broker}:{self.mqtt_port}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка подключения MQTT: {e}")
            self.mqtt_client = None
    
    def on_mqtt_connect(self, client, userdata, flags, reason_code=None, properties=None):
        """Callback при подключении к MQTT брокеру (API v2 compatible)"""
        # Support both API v1 (rc in flags) and v2 (reason_code)
        if reason_code is not None:
            # API v2: reason_code is separate parameter
            rc = reason_code
        elif isinstance(flags, dict):
            # API v2: flags is dict, check reason_code
            rc = flags.get('reason_code', 0) if 'reason_code' in flags else 0
        else:
            # API v1: flags contains rc
            rc = flags if isinstance(flags, int) else 0
            
        if rc == 0:
            self.logger.info(f"✅ MQTT подключено успешно")
        else:
            self.logger.error(f"❌ MQTT подключение неудачно, код: {rc}")
    
    def on_mqtt_disconnect(self, client, userdata, *args, **kwargs):
        """Callback при отключении от MQTT брокера (API v1/v2 compatible)"""
        # Handle different API versions:
        # API v1: on_disconnect(client, userdata, rc)
        # API v2: on_disconnect(client, userdata, rc, properties=None) 
        #        or on_disconnect(client, userdata, rc, flags, properties)
        rc = 0
        
        if args:
            # First positional argument after client, userdata is usually rc/reason_code
            rc = args[0] if isinstance(args[0], int) else 0
        elif 'reason_code' in kwargs:
            rc = kwargs['reason_code']
        elif 'rc' in kwargs:
            rc = kwargs['rc']
            
        if rc != 0:
            self.logger.warning(f"⚠️  Неожиданное отключение MQTT, код: {rc}")
    
    def publish_mqtt(self, telemetry):
        """Публикация телеметрии в MQTT"""
        if not self.mqtt_client:
            return
        
        try:
            payload = json.dumps(asdict(telemetry), ensure_ascii=False)
            result = self.mqtt_client.publish(self.mqtt_topic, payload, qos=1)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.debug(f"📤 MQTT: опубликовано в {self.mqtt_topic}")
            else:
                self.logger.warning(f"⚠️  MQTT: ошибка публикации, код: {result.rc}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка MQTT публикации: {e}")
    
    def update_prometheus_metrics(self, telemetry):
        """Обновление метрик Prometheus"""
        try:
            self.prom_input_voltage.set(telemetry.input_voltage)
            self.prom_output_voltage.set(telemetry.output_voltage)
            self.prom_battery_voltage.set(telemetry.battery_voltage)
            self.prom_battery_level.labels(status=telemetry.status).set(telemetry.battery_level)
            self.prom_load_percent.set(telemetry.load_percent)
            self.prom_load_power.set(telemetry.load_power)
            self.prom_frequency.set(telemetry.frequency)
            self.prom_input_frequency.set(telemetry.input_frequency)
            self.prom_temperature.set(telemetry.temperature)
            
            # Status: 1 for online, 0 for battery
            # Cache labels to avoid recreating
            status_label = telemetry.status
            if status_label not in self._status_labels:
                self._status_labels[status_label] = self.prom_status.labels(status=status_label)
            
            status_value = 1.0 if telemetry.status == "online" else 0.0
            self._status_labels[status_label].set(status_value)
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления Prometheus метрик: {e}")

    def wakeup_ups(self):
        """Пробуждение UPS"""
        self.logger.debug("Пробуждение UPS...")

        for hex_cmd in WAKEUP_COMMANDS:
            try:
                cmd = bytes.fromhex(hex_cmd)
                self.ser.write(cmd)
                self.ser.flush()
                time.sleep(WAKEUP_DELAY)
                self.ser.read(100)
            except Exception as e:
                self.logger.warning(f"Ошибка при пробуждении: {e}")
                return False

        time.sleep(POST_WAKEUP_DELAY)
        return True

    def send_command(self, hex_command, description=""):
        """Отправка команды и чтение ответа"""
        try:
            cmd = bytes.fromhex(hex_command)
            self.ser.write(cmd)
            self.ser.flush()
            time.sleep(0.5)

            response = self.ser.read(100)
            return response if response else None

        except Exception as e:
            self.logger.error(f"Ошибка команды {description}: {e}")
            return None

    def parse_telemetry(self, data):
        """Парсинг телеметрии из данных"""
        # Use experimental Modbus parser if enabled
        if self.use_modbus_parser:
            return self._parse_telemetry_modbus(data)
        else:
            return self._parse_telemetry_legacy(data)
    
    def _parse_telemetry_legacy(self, data):
        """Legacy parser using range matching"""
        telemetry = UPSTelemetry()
        telemetry.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        telemetry.uptime = self.get_uptime()

        if len(data) < 5:
            return telemetry

        payload = data[5:]

        # Парсим как big-endian
        values = []
        for i in range(0, len(payload) - 1, 2):
            values.append(struct.unpack_from('>H', payload, i)[0])

        # Parse values using range matching
        for val in values:
            # Output voltage (220-230V) - first occurrence (output comes first in UPS data)
            if VOLTAGE_RANGE[0] <= val <= VOLTAGE_RANGE[1] and telemetry.output_voltage == 0:
                telemetry.output_voltage = val / 10.0
            # Input voltage (220-230V) - second occurrence (input comes second in UPS data)
            elif VOLTAGE_RANGE[0] <= val <= VOLTAGE_RANGE[1] and telemetry.output_voltage > 0:
                telemetry.input_voltage = val / 10.0
            # Frequency (49-51Hz)
            elif FREQUENCY_RANGE[0] <= val <= FREQUENCY_RANGE[1]:
                telemetry.frequency = val / 10.0
                telemetry.input_frequency = val / 10.0
            # Battery voltage (13-14V)
            elif BATTERY_VOLTAGE_RANGE[0] <= val <= BATTERY_VOLTAGE_RANGE[1]:
                telemetry.battery_voltage = val / 10.0
            # Battery level (95-105%)
            elif BATTERY_LEVEL_RANGE[0] <= val <= BATTERY_LEVEL_RANGE[1]:
                telemetry.battery_level = val
            # Load percentage (10-20%)
            elif LOAD_PERCENT_RANGE[0] <= val <= LOAD_PERCENT_RANGE[1]:
                telemetry.load_percent = val
            # Load power (130-150W)
            elif LOAD_POWER_RANGE[0] <= val <= LOAD_POWER_RANGE[1]:
                telemetry.load_power = val
            # Temperature (30-40°C)
            elif TEMPERATURE_RANGE[0] <= val <= TEMPERATURE_RANGE[1]:
                telemetry.temperature = val

        # Determine status based on input voltage
        telemetry.status = "online" if telemetry.input_voltage > ONLINE_VOLTAGE_THRESHOLD else "battery"

        return telemetry
    
    def _parse_telemetry_modbus(self, data):
        """Experimental Modbus-based parser"""
        try:
            modbus_telemetry = parse_telemetry_modbus(data, self.get_uptime())
            
            # Convert Modbus telemetry to standard structure
            telemetry = UPSTelemetry()
            telemetry.timestamp = modbus_telemetry.timestamp
            telemetry.uptime = modbus_telemetry.uptime
            telemetry.input_voltage = modbus_telemetry.input_voltage
            telemetry.output_voltage = modbus_telemetry.output_voltage
            telemetry.battery_voltage = modbus_telemetry.battery_voltage
            telemetry.battery_level = modbus_telemetry.battery_level
            telemetry.load_percent = modbus_telemetry.load_percent
            telemetry.load_power = modbus_telemetry.load_power
            telemetry.frequency = modbus_telemetry.frequency
            telemetry.input_frequency = modbus_telemetry.input_frequency
            telemetry.temperature = modbus_telemetry.temperature
            telemetry.status = modbus_telemetry.status
            
            # Log extended values if available
            if modbus_telemetry.error_message and modbus_telemetry.error_message != "No errors":
                self.logger.warning(f"UPS Error: {modbus_telemetry.error_message}")
            if modbus_telemetry.warning_message and modbus_telemetry.warning_message != "No errors":
                self.logger.warning(f"UPS Warning: {modbus_telemetry.warning_message}")
            
            return telemetry
        except Exception as e:
            self.logger.error(f"❌ Error in Modbus parser: {e}", exc_info=True)
            # Fallback to legacy parser
            return self._parse_telemetry_legacy(data)

    def get_telemetry(self):
        """Получение полной телеметрии"""
        telemetry = UPSTelemetry()

        # Get main parameters
        response = self.send_command(UPS_COMMAND_MAIN_PARAMS, "основные параметры")
        if response:
            telemetry = self.parse_telemetry(response)

        # If battery data missing, try battery command
        if telemetry.battery_voltage == 0:
            battery_response = self.send_command(UPS_COMMAND_BATTERY, "батарея")
            if battery_response:
                battery_telemetry = self.parse_telemetry(battery_response)
                if battery_telemetry.battery_voltage > 0:
                    telemetry.battery_voltage = battery_telemetry.battery_voltage
                if battery_telemetry.battery_level > 0:
                    telemetry.battery_level = battery_telemetry.battery_level

        return telemetry

    def check_alarms(self, telemetry):
        """Проверка аварийных состояний"""
        alarms = []

        if telemetry.input_voltage > 0 and telemetry.input_voltage < MIN_INPUT_VOLTAGE:
            alarms.append("Низкое напряжение сети")

        if telemetry.battery_level > 0 and telemetry.battery_level < MIN_BATTERY_LEVEL:
            alarms.append("Низкий заряд батареи")

        if telemetry.temperature > 0 and telemetry.temperature > MAX_TEMPERATURE:
            alarms.append("Высокая температура")

        if telemetry.load_percent > 0 and telemetry.load_percent > MAX_LOAD_PERCENT:
            alarms.append("Высокая нагрузка")

        return alarms

    def monitoring_loop(self):
        """Цикл мониторинга UPS"""
        self.logger.info(f"🔍 Запуск цикла мониторинга (интервал: {self.interval} сек)")

        while self.running:
            try:
                # Connect if needed
                if not self.ser or not self.ser.is_open:
                    if not self.connect():
                        self.logger.warning(f"Ожидание {CONNECTION_RETRY_DELAY} секунд перед повторной попыткой...")
                        time.sleep(CONNECTION_RETRY_DELAY)
                        continue

                # Wake up UPS
                if not self.wakeup_ups():
                    self.logger.error("Не удалось пробудить UPS, переподключаемся...")
                    self.disconnect()
                    time.sleep(ERROR_RETRY_DELAY)
                    continue

                # Получение телеметрии
                telemetry = self.get_telemetry()

                # Обновление текущей телеметрии
                if any([telemetry.input_voltage > 0, telemetry.battery_voltage > 0]):
                    self.current_telemetry = telemetry

                    # Обновление Prometheus метрик
                    self.update_prometheus_metrics(telemetry)

                    # Публикация в MQTT
                    self.publish_mqtt(telemetry)

                    # Логирование
                    self.logger.info(
                        f"Телеметрия: "
                        f"Vin={telemetry.input_voltage:.1f}V, "
                        f"Vout={telemetry.output_voltage:.1f}V, "
                        f"Batt={telemetry.battery_voltage:.1f}V, "
                        f"Load={telemetry.load_percent}%"
                    )

                    # Проверка аварий
                    alarms = self.check_alarms(telemetry)
                    for alarm in alarms:
                        self.logger.warning(f"Авария: {alarm}")

                else:
                    self.logger.warning("Не удалось получить телеметрию")

                # Ожидание до следующего опроса
                for i in range(self.interval):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                self.logger.error(f"Ошибка в цикле мониторинга: {e}", exc_info=True)
                self.disconnect()
                time.sleep(ERROR_RETRY_DELAY)

class UPSRequestHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP запросов"""

    def __init__(self, *args, **kwargs):
        self.daemon = kwargs.pop('daemon')
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        self.daemon.logger.info(f"WEB {self.address_string()} - {format % args}")

    def _safe_write(self, data):
        """Safely write data to client, handling connection errors gracefully"""
        try:
            if isinstance(data, str):
                self.wfile.write(data.encode())
            else:
                self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            # Client disconnected before we finished sending
            # This is normal and not an error worth logging
            self.daemon.logger.debug(f"Client disconnected during write: {type(e).__name__}")
        except Exception as e:
            self.daemon.logger.error(f"Unexpected error writing to client: {e}")

    def do_GET(self):
        try:
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()

                telemetry = self.daemon.current_telemetry
                alarms = self.daemon.check_alarms(telemetry)

                html = self.generate_html(telemetry, alarms)
                self._safe_write(html)

            elif self.path == '/api/telemetry':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()

                telemetry_dict = asdict(self.daemon.current_telemetry)
                telemetry_dict['alarms'] = self.daemon.check_alarms(self.daemon.current_telemetry)
                response = json.dumps(telemetry_dict, indent=2)
                self._safe_write(response)

            elif self.path == '/api/health':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()

                health = {
                    'status': 'running',
                    'uptime': self.daemon.get_uptime(),
                    'timestamp': datetime.now().isoformat()
                }
                self._safe_write(json.dumps(health))

            elif self.path == '/metrics':
                self.send_response(200)
                self.send_header('Content-type', CONTENT_TYPE_LATEST)
                self.end_headers()
                self._safe_write(generate_latest())

            else:
                self.send_response(404)
                self.end_headers()
                self._safe_write(b'404 Not Found')
        except Exception as e:
            self.daemon.logger.error(f"Error handling request {self.path}: {e}", exc_info=True)
            try:
                self.send_response(500)
                self.end_headers()
                self._safe_write(json.dumps({'error': 'Internal server error'}).encode())
            except:
                pass  # Client may have already disconnected

    def generate_html(self, telemetry, alarms):
        status_color = "green" if telemetry.status == "online" else "red"
        status_text = "ONLINE" if telemetry.status == "online" else "BATTERY"

        return f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UPS Monitor</title>
    <style>
        body {{
            font-family: 'Arial', sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        .header {{
            background: #2c3e50;
            color: white;
            padding: 20px;
            text-align: center;
        }}
        .status {{
            background: {status_color};
            color: white;
            padding: 10px;
            text-align: center;
            font-size: 1.2em;
            font-weight: bold;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            padding: 20px;
        }}
        .card {{
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            border-left: 4px solid #3498db;
            transition: transform 0.3s;
        }}
        .card:hover {{
            transform: translateY(-5px);
        }}
        .card h3 {{
            margin: 0 0 10px 0;
            color: #2c3e50;
        }}
        .value {{
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }}
        .unit {{
            font-size: 0.8em;
            color: #7f8c8d;
        }}
        .alarms {{
            background: #e74c3c;
            color: white;
            padding: 15px;
            margin: 20px;
            border-radius: 10px;
            display: {'' if alarms else 'none'};
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
            border-top: 1px solid #ecf0f1;
        }}
        .battery {{
            background: linear-gradient(90deg, #2ecc71 {telemetry.battery_level}%, #ecf0f1 {telemetry.battery_level}%);
            height: 30px;
            border-radius: 15px;
            margin: 10px 0;
            position: relative;
            border: 2px solid #34495e;
        }}
        .battery-level {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-weight: bold;
            color: #2c3e50;
            text-shadow: 1px 1px 2px white;
        }}
        .auto-refresh {{
            text-align: center;
            padding: 10px;
            background: #ecf0f1;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .card {{
            animation: fadeIn 0.5s ease-out;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔋 MUST EP20-1000-Pro Monitoring System</h1>
            <p>Real-time telemetry data</p>
        </div>

        <div class="status">
            Status: {status_text} | Last Update: {telemetry.timestamp} | Uptime: {telemetry.uptime}
        </div>

        {''.join(f'<div class="alarms">🚨 {alarm}</div>' for alarm in alarms)}

        <div class="grid">
            <div class="card">
                <h3>⚡ Input Voltage</h3>
                <div class="value">{telemetry.input_voltage:.1f}<span class="unit">V</span></div>
            </div>

            <div class="card">
                <h3>🔌 Output Voltage</h3>
                <div class="value">{telemetry.output_voltage:.1f}<span class="unit">V</span></div>
            </div>

            <div class="card">
                <h3>🔄 Frequency</h3>
                <div class="value">{telemetry.frequency:.1f}<span class="unit">Hz</span></div>
            </div>

            <div class="card">
                <h3>🔋 Battery Voltage</h3>
                <div class="value">{telemetry.battery_voltage:.1f}<span class="unit">V</span></div>
            </div>

            <div class="card">
                <h3>📈 Battery Level</h3>
                <div class="value">{telemetry.battery_level}<span class="unit">%</span></div>
                <div class="battery">
                    <div class="battery-level">{telemetry.battery_level}%</div>
                </div>
            </div>

            <div class="card">
                <h3>💪 Load Power</h3>
                <div class="value">{telemetry.load_power}<span class="unit">W</span></div>
            </div>

            <div class="card">
                <h3>📊 Load Percentage</h3>
                <div class="value">{telemetry.load_percent}<span class="unit">%</span></div>
            </div>

            <div class="card">
                <h3>🌡️ Temperature</h3>
                <div class="value">{telemetry.temperature:.1f}<span class="unit">°C</span></div>
            </div>
        </div>

        <div class="auto-refresh">
            <p>🔄 Auto-refresh every 10 seconds |
               <a href="/api/telemetry" target="_blank">JSON API</a> |
               <a href="/api/health" target="_blank">Health Check</a>
            </p>
        </div>

        <div class="footer">
            <p> Data updates every {self.daemon.interval} seconds</p>
        </div>
    </div>

    <script>
        // Auto-refresh page every 10 seconds
        setTimeout(() => location.reload(), 10000);

        // Add animations
        document.addEventListener('DOMContentLoaded', function() {{
            const cards = document.querySelectorAll('.card');
            cards.forEach((card, index) => {{
                card.style.animationDelay = (index * 0.1) + 's';
            }});
        }});
    </script>
</body>
</html>
"""

def load_config(config_path=None):
    """Загрузка конфигурации из YAML файла"""
    if config_path is None:
        # Попытка найти конфиг в стандартных местах
        possible_paths = [
            'config.yaml',
            'config.yml',
            os.path.expanduser('~/.ups_monitor/config.yaml'),
            '/etc/ups_monitor/config.yaml'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                config_path = path
                break
    
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return config
        except Exception as e:
            print(f"⚠️  Ошибка чтения конфига {config_path}: {e}")
            return {}
    
    return {}

def get_config_value(config, *keys, default=None):
    """Получение значения из вложенного словаря конфига"""
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current if current is not None else default

def start_web_server(daemon, port=8080):
    """Запуск веб-сервера в отдельном потоке"""
    handler = lambda *args, **kwargs: UPSRequestHandler(*args, daemon=daemon, **kwargs)
    server = HTTPServer(('0.0.0.0', port), handler)
    
    # Store server reference in daemon for shutdown
    daemon.web_server = server

    daemon.logger.info(f"🌐 Веб-сервер запущен на http://0.0.0.0:{port}")
    daemon.logger.info("   Доступные endpoints:")
    daemon.logger.info("   - / : Веб-интерфейс")
    daemon.logger.info("   - /api/telemetry : JSON API")
    daemon.logger.info("   - /api/health : Health check")
    daemon.logger.info("   - /metrics : Prometheus metrics")

    def run_server():
        """Запуск сервера в отдельном потоке"""
        try:
            server.serve_forever(poll_interval=1)
        except Exception as e:
            if daemon.running:  # Only log if we're still supposed to be running
                daemon.logger.error(f"Ошибка веб-сервера: {e}")
        finally:
            daemon.logger.info("Веб-сервер остановлен")
            server.server_close()
    
    # Start server in daemon thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    return server_thread

def main():
    parser = argparse.ArgumentParser(
        description='UPS Monitoring Daemon with Web Interface, Prometheus metrics and MQTT support',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # С использованием конфиг-файла (рекомендуется)
  python3 mustmon.py --config config.yaml
  
  # С параметрами командной строки
  python3 mustmon.py /dev/ttyUSB0
  python3 mustmon.py /dev/ttyUSB0 --web-port 9000
  python3 mustmon.py /dev/ttyUSB0 --mqtt-broker mqtt.example.com
  
  # Комбинация конфиг-файла и параметров командной строки
  python3 mustmon.py --config config.yaml --web-port 9000
        """
    )
    
    parser.add_argument('port', nargs='?', help='Serial port (e.g., /dev/ttyUSB0)')
    parser.add_argument('--config', '-c', help='Path to configuration file (YAML)')
    parser.add_argument('--web-port', type=int, help='Web server port')
    parser.add_argument('--interval', type=int, help='Polling interval in seconds')
    parser.add_argument('--mqtt-broker', help='MQTT broker address')
    parser.add_argument('--mqtt-port', type=int, help='MQTT broker port')
    parser.add_argument('--mqtt-topic', help='MQTT topic')
    parser.add_argument('--mqtt-username', help='MQTT username')
    parser.add_argument('--mqtt-password', help='MQTT password')
    parser.add_argument('--use-modbus-parser', action='store_true', 
                       help='Use experimental Modbus parser (requires ups_modbus_parser.py)')
    
    args = parser.parse_args()
    
    # Загрузка конфига
    config = load_config(args.config)
    
    # Приоритет: CLI аргументы > конфиг > значения по умолчанию
    port = args.port or get_config_value(config, 'serial', 'port')
    if not port:
        print("❌ Порт не указан! Используйте --config или укажите порт как аргумент")
        parser.print_help()
        sys.exit(1)
    
    web_port = args.web_port or get_config_value(config, 'web', 'port', default=8080)
    interval = args.interval or get_config_value(config, 'monitoring', 'interval', default=30)
    max_errors = get_config_value(config, 'monitoring', 'max_errors', default=5)
    
    # MQTT настройки
    mqtt_enabled = get_config_value(config, 'mqtt', 'enabled', default=False)
    # Если broker указан в CLI или конфиге, используем его (CLI имеет приоритет)
    mqtt_broker = args.mqtt_broker
    if not mqtt_broker and mqtt_enabled:
        mqtt_broker = get_config_value(config, 'mqtt', 'broker', default='localhost')
    elif not mqtt_broker:
        # Проверяем, есть ли broker в конфиге даже если enabled=False
        mqtt_broker = get_config_value(config, 'mqtt', 'broker')
    
    mqtt_port = args.mqtt_port or get_config_value(config, 'mqtt', 'port', default=1883)
    mqtt_topic = args.mqtt_topic or get_config_value(config, 'mqtt', 'topic', default='ups/telemetry')
    mqtt_username = args.mqtt_username or get_config_value(config, 'mqtt', 'username')
    mqtt_password = args.mqtt_password or get_config_value(config, 'mqtt', 'password')
    
    # Настройки логирования
    log_level_str = get_config_value(config, 'logging', 'level', default='INFO')
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    log_file = get_config_value(config, 'logging', 'file', default='/tmp/ups_web_daemon.log')
    log_console = get_config_value(config, 'logging', 'console', default=True)
    
    # Parser selection
    use_modbus_parser = args.use_modbus_parser or get_config_value(config, 'monitoring', 'use_modbus_parser', default=False)

    # Проверка доступности порта
    if not os.path.exists(port):
        print(f"❌ Порт {port} не существует")
        sys.exit(1)

    print(f"🔌 UPS Web Monitoring Daemon")
    if args.config or config:
        config_used = args.config if args.config else 'config.yaml (auto-detected)'
        print(f"   Config file: {config_used}")
    print(f"   Serial port: {port}")
    print(f"   Web interface: http://0.0.0.0:{web_port}")
    print(f"   Polling interval: {interval} сек")
    if mqtt_broker:
        print(f"   MQTT broker: {mqtt_broker}:{mqtt_port}")
        print(f"   MQTT topic: {mqtt_topic}")
    else:
        print(f"   MQTT: disabled")
    print(f"   Log level: {log_level_str}")
    print(f"   Log file: {log_file}")
    print("=" * 50)

    # Запуск демона
    daemon = UPSWebDaemon(port, web_port, interval, 
                         mqtt_broker, mqtt_port, mqtt_topic,
                         mqtt_username, mqtt_password,
                         log_level, log_file, log_console, max_errors,
                         use_modbus_parser)

    # Запуск мониторинга в отдельном потоке
    monitor_thread = threading.Thread(target=daemon.monitoring_loop, daemon=True)
    monitor_thread.start()

    # Запуск веб-сервера в отдельном потоке
    server_thread = start_web_server(daemon, web_port)
    
    try:
        # Основной поток ждет завершения или сигнала
        while daemon.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        daemon.logger.info("Получен KeyboardInterrupt")
        daemon.running = False
    finally:
        # Завершение работы
        daemon.logger.info("Завершение работы демона...")
        daemon.running = False
        
        # Stop web server (must be called from different thread)
        if daemon.web_server:
            daemon.logger.info("Остановка веб-сервера...")
            try:
                daemon.web_server.shutdown()
            except Exception as e:
                daemon.logger.error(f"Ошибка при остановке веб-сервера: {e}")
        
        # Wait for server thread to finish
        if server_thread.is_alive():
            daemon.logger.info("Ожидание завершения потока веб-сервера...")
            server_thread.join(timeout=3)
        
        # Wait for monitor thread to finish (with timeout)
        if monitor_thread.is_alive():
            daemon.logger.info("Ожидание завершения потока мониторинга...")
            monitor_thread.join(timeout=5)
            if monitor_thread.is_alive():
                daemon.logger.warning("Поток мониторинга не завершился в течение 5 секунд")
        
        # Cleanup MQTT
        if daemon.mqtt_client:
            try:
                daemon.mqtt_client.loop_stop()
                daemon.mqtt_client.disconnect()
            except Exception as e:
                daemon.logger.error(f"Ошибка при отключении MQTT: {e}")
        
        # Disconnect from UPS
        daemon.disconnect()
        daemon.logger.info("👋 UPS Web Daemon завершил работу")

if __name__ == "__main__":
    main()
