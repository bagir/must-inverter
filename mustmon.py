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
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

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
    def __init__(self, port, web_port=8080, interval=30):
        self.port = port
        self.web_port = web_port
        self.interval = interval
        self.ser = None
        self.running = True
        self.connection_errors = 0
        self.max_errors = 5
        self.current_telemetry = UPSTelemetry()
        self.start_time = datetime.now()

        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('/tmp/ups_web_daemon.log', mode='a')
            ]
        )
        self.logger = logging.getLogger('UPSWebDaemon')

        # Обработчик сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Обработчик сигналов для graceful shutdown"""
        self.logger.info(f"Получен сигнал {signum}, завершаем работу...")
        self.running = False

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
                baudrate=9600,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=2
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

    def wakeup_ups(self):
        """Пробуждение UPS"""
        wakeup_commands = [
            "0103271000018f7b",
            "05034e210001c2ac",
            "06034e210001c29f",
            "0a03753000019f72",
        ]

        self.logger.debug("Пробуждение UPS...")

        for hex_cmd in wakeup_commands:
            try:
                cmd = bytes.fromhex(hex_cmd)
                self.ser.write(cmd)
                self.ser.flush()
                time.sleep(0.3)
                self.ser.read(100)
            except Exception as e:
                self.logger.warning(f"Ошибка при пробуждении: {e}")
                return False

        time.sleep(0.5)
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

        # Поиск значений в данных
        for i, val in enumerate(values):
            # Напряжение сети (220-230V)
            if 2200 <= val <= 2300 and telemetry.input_voltage == 0:
                telemetry.input_voltage = val / 10.0

            # Напряжение выхода (220-230V)
            elif 2200 <= val <= 2300 and telemetry.input_voltage > 0:
                telemetry.output_voltage = val / 10.0

            # Частота (49-51Hz)
            elif 490 <= val <= 510:
                telemetry.frequency = val / 10.0
                telemetry.input_frequency = val / 10.0

            # Напряжение батареи (13-14V)
            elif 130 <= val <= 140:
                telemetry.battery_voltage = val / 10.0

            # Уровень батареи (95-105%)
            elif 95 <= val <= 105:
                telemetry.battery_level = val

            # Процент нагрузки (10-20%)
            elif 10 <= val <= 20:
                telemetry.load_percent = val

            # Мощность нагрузки (130-150W)
            elif 130 <= val <= 150:
                telemetry.load_power = val

            # Температура (30-40°C)
            elif 30 <= val <= 40:
                telemetry.temperature = val

        # Определение статуса на основе телеметрии
        if telemetry.input_voltage > 200:
            telemetry.status = "online"
        else:
            telemetry.status = "battery"

        return telemetry

    def get_telemetry(self):
        """Получение полной телеметрии"""
        telemetry = UPSTelemetry()

        # Основные параметры
        response = self.send_command("0a037530001b1eb9", "основные параметры")
        if response:
            telemetry = self.parse_telemetry(response)

        # Если не получили данные, пробуем запрос батареи
        if telemetry.battery_voltage == 0:
            battery_response = self.send_command("0a037918000a5ded", "батарея")
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

        if telemetry.input_voltage < 180:
            alarms.append("Низкое напряжение сети")

        if telemetry.battery_level < 20:
            alarms.append("Низкий заряд батареи")

        if telemetry.temperature > 40:
            alarms.append("Высокая температура")

        if telemetry.load_percent > 80:
            alarms.append("Высокая нагрузка")

        return alarms

    def monitoring_loop(self):
        """Цикл мониторинга UPS"""
        self.logger.info(f"🔍 Запуск цикла мониторинга (интервал: {self.interval} сек)")

        while self.running:
            try:
                # Подключаемся если нужно
                if not self.ser or not self.ser.is_open:
                    if not self.connect():
                        self.logger.warning("Ожидание 10 секунд перед повторной попыткой...")
                        time.sleep(10)
                        continue

                # Пробуждение UPS
                if not self.wakeup_ups():
                    self.logger.error("Не удалось пробудить UPS, переподключаемся...")
                    self.disconnect()
                    time.sleep(5)
                    continue

                # Получение телеметрии
                telemetry = self.get_telemetry()

                # Обновление текущей телеметрии
                if any([telemetry.input_voltage > 0, telemetry.battery_voltage > 0]):
                    self.current_telemetry = telemetry

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
                self.logger.error(f"Ошибка в цикле мониторинга: {e}")
                self.disconnect()
                time.sleep(5)

class UPSRequestHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP запросов"""

    def __init__(self, *args, **kwargs):
        self.daemon = kwargs.pop('daemon')
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        self.daemon.logger.info(f"WEB {self.address_string()} - {format % args}")

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            telemetry = self.daemon.current_telemetry
            alarms = self.daemon.check_alarms(telemetry)

            html = self.generate_html(telemetry, alarms)
            self.wfile.write(html.encode())

        elif self.path == '/api/telemetry':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            telemetry_dict = asdict(self.daemon.current_telemetry)
            telemetry_dict['alarms'] = self.daemon.check_alarms(self.daemon.current_telemetry)
            response = json.dumps(telemetry_dict, indent=2)
            self.wfile.write(response.encode())

        elif self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            health = {
                'status': 'running',
                'uptime': self.daemon.get_uptime(),
                'timestamp': datetime.now().isoformat()
            }
            self.wfile.write(json.dumps(health).encode())

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'404 Not Found')

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

def start_web_server(daemon, port=8080):
    """Запуск веб-сервера"""
    handler = lambda *args, **kwargs: UPSRequestHandler(*args, daemon=daemon, **kwargs)
    server = HTTPServer(('0.0.0.0', port), handler)

    daemon.logger.info(f"🌐 Веб-сервер запущен на http://0.0.0.0:{port}")
    daemon.logger.info("   Доступные endpoints:")
    daemon.logger.info("   - / : Веб-интерфейс")
    daemon.logger.info("   - /api/telemetry : JSON API")
    daemon.logger.info("   - /api/health : Health check")

    try:
        server.serve_forever()
    except Exception as e:
        daemon.logger.error(f"Ошибка веб-сервера: {e}")
    finally:
        server.server_close()

def main():
    if len(sys.argv) not in [2, 3, 4]:
        print("Использование: python3 ups_web_daemon_fixed.py /dev/ttyUSB0 [web_port] [interval]")
        print("Примеры:")
        print("  python3 ups_web_daemon_fixed.py /dev/ttyUSB0")
        print("  python3 ups_web_daemon_fixed.py /dev/ttyUSB0 8080")
        print("  python3 ups_web_daemon_fixed.py /dev/ttyUSB0 8080 30")
        sys.exit(1)

    port = sys.argv[1]
    web_port = 8080
    interval = 30

    if len(sys.argv) >= 3:
        web_port = int(sys.argv[2])
    if len(sys.argv) >= 4:
        interval = int(sys.argv[3])

    # Проверка доступности порта
    import os
    if not os.path.exists(port):
        print(f"❌ Порт {port} не существует")
        sys.exit(1)

    print(f"🔌 UPS Web Monitoring Daemon")
    print(f"   Serial port: {port}")
    print(f"   Web interface: http://0.0.0.0:{web_port}")
    print(f"   Polling interval: {interval} сек")
    print(f"   Log file: /tmp/ups_web_daemon.log")
    print("=" * 50)

    # Запуск демона
    daemon = UPSWebDaemon(port, web_port, interval)

    # Запуск мониторинга в отдельном потоке
    monitor_thread = threading.Thread(target=daemon.monitoring_loop, daemon=True)
    monitor_thread.start()

    # Запуск веб-сервера в основном потоке
    start_web_server(daemon, web_port)

    # Завершение работы
    daemon.disconnect()
    daemon.logger.info("👋 UPS Web Daemon завершил работу")

if __name__ == "__main__":
    main()
