# MUST EP 20 1000 UPS Monitoring System

Comprehensive UPS (Uninterruptible Power Supply) monitoring system with web interface, Prometheus metrics, MQTT integration, and JSON API.

## 📋 Features

- 🔄 **Automatic polling** of UPS every 30 seconds (configurable)
- 🌐 **Web interface** with beautiful real-time data visualization
- 📊 **JSON API** for integration with other systems
- 📈 **Prometheus metrics** export for monitoring stacks
- 📡 **MQTT integration** for IoT platforms and Home Assistant
- 🚨 **Alert system** for problem detection
- 🔧 **Automatic reconnection** on communication errors
- 📝 **Comprehensive logging** with configurable levels
- ⚙️ **YAML configuration file** support
- 🐳 **Docker support** with optimized multi-stage build

## 📊 Monitored Parameters

- ⚡ Input voltage (V)
- 🔌 Output voltage (V)
- 🔄 Frequency (Hz)
- 🔋 Battery voltage (V)
- 📈 Battery level (%)
- 💪 Load power (Watts)
- 📊 Load percentage (%)
- 🌡️ Temperature (°C)
- 📍 UPS status (online/battery)

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Build image
docker build -t ups-monitor .

# Run with default settings
docker run -d --name ups-monitor \
  --device=/dev/ttyUSB0:/dev/ttyUSB0 \
  -p 8080:8080 \
  ups-monitor

# Or use docker-compose
cp config.yaml.example config.yaml
# Edit config.yaml
docker-compose up -d
```

### Option 2: Native Installation

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run with default settings
python3 mustmon.py /dev/ttyUSB0

# Or with configuration file
cp config.yaml.example config.yaml
# Edit config.yaml
python3 mustmon.py --config config.yaml
```

### Access Web Interface

Open in your browser:
```
http://localhost:8080
```

## ⚙️ Configuration

### Configuration File (Recommended)

The system supports YAML configuration files for easier management:

```bash
# Copy example configuration
cp config.yaml.example config.yaml

# Edit configuration
nano config.yaml
```

**Example `config.yaml`:**
```yaml
serial:
  port: /dev/ttyUSB0

web:
  port: 8080

monitoring:
  interval: 30
  max_errors: 5

mqtt:
  enabled: true
  broker: mqtt.example.com
  port: 1883
  topic: ups/telemetry
  username: mqtt_user
  password: mqtt_password

logging:
  level: INFO
  file: /tmp/ups_web_daemon.log
  console: true
```

**Configuration file locations (auto-detected):**
1. `config.yaml` in current directory
2. `config.yml` in current directory
3. `~/.ups_monitor/config.yaml`
4. `/etc/ups_monitor/config.yaml`

Or specify explicitly:
```bash
python3 mustmon.py --config /path/to/config.yaml
```

### Command Line Parameters

All parameters can be overridden via command line:

```bash
# Basic usage
python3 mustmon.py /dev/ttyUSB0

# With custom web port
python3 mustmon.py /dev/ttyUSB0 --web-port 9000

# With custom polling interval
python3 mustmon.py /dev/ttyUSB0 --interval 60

# With MQTT
python3 mustmon.py /dev/ttyUSB0 --mqtt-broker mqtt.example.com

# Full example
python3 mustmon.py /dev/ttyUSB0 \
  --web-port 8080 \
  --interval 30 \
  --mqtt-broker mqtt.example.com \
  --mqtt-port 1883 \
  --mqtt-topic ups/telemetry \
  --mqtt-username user \
  --mqtt-password pass
```

**Available command line options:**
- `--config, -c` - Path to configuration file (YAML)
- `--web-port` - Web server port (default: 8080)
- `--interval` - Polling interval in seconds (default: 30)
- `--mqtt-broker` - MQTT broker address
- `--mqtt-port` - MQTT broker port (default: 1883)
- `--mqtt-topic` - MQTT topic (default: ups/telemetry)
- `--mqtt-username` - MQTT username
- `--mqtt-password` - MQTT password

**Priority:** CLI arguments > Config file > Default values

### Running in Background

```bash
# Using systemd (create service file)
sudo nano /etc/systemd/system/ups-monitor.service

[Unit]
Description=UPS Monitoring Daemon
After=network.target

[Service]
Type=simple
User=upsmonitor
WorkingDirectory=/opt/ups-monitor
ExecStart=/usr/bin/python3 /opt/ups-monitor/mustmon.py --config /etc/ups_monitor/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl enable ups-monitor
sudo systemctl start ups-monitor

# Or using nohup
nohup python3 mustmon.py --config config.yaml > /dev/null 2>&1 &
```

## 🌐 Web Interface

### Main Page
- **URL**: `http://localhost:8080/`
- **Description**: Real-time web dashboard with data cards
- **Auto-refresh**: Every 10 seconds

### API Endpoints

#### Get Telemetry
```bash
curl http://localhost:8080/api/telemetry
```

**Response:**
```json
{
  "input_voltage": 225.6,
  "output_voltage": 224.8,
  "battery_voltage": 13.6,
  "battery_level": 100,
  "load_percent": 14,
  "load_power": 138,
  "frequency": 50.1,
  "input_frequency": 50.1,
  "temperature": 33.0,
  "timestamp": "2024-01-15 14:30:25",
  "status": "online",
  "uptime": "02:15:30",
  "alarms": []
}
```

#### Health Check
```bash
curl http://localhost:8080/api/health
```

**Response:**
```json
{
  "status": "running",
  "uptime": "02:15:30",
  "timestamp": "2024-01-15T14:30:25.123456"
}
```

#### Prometheus Metrics
```bash
curl http://localhost:8080/metrics
```

**Example metrics:**
```
# HELP ups_input_voltage Input voltage in volts
# TYPE ups_input_voltage gauge
ups_input_voltage 225.6

# HELP ups_battery_level Battery level in percent
# TYPE ups_battery_level gauge
ups_battery_level{status="online"} 100

# HELP ups_status UPS status (1=online, 0=battery)
# TYPE ups_status gauge
ups_status{status="online"} 1.0
```

## 📈 Prometheus Integration

### Prometheus Configuration

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'ups'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 30s
    metrics_path: '/metrics'
```

### Available Metrics

- `ups_input_voltage` - Input voltage in volts (gauge)
- `ups_output_voltage` - Output voltage in volts (gauge)
- `ups_battery_voltage` - Battery voltage in volts (gauge)
- `ups_battery_level{status}` - Battery level in percent (gauge)
- `ups_load_percent` - Load percentage (gauge)
- `ups_load_power` - Load power in watts (gauge)
- `ups_frequency` - Frequency in Hz (gauge)
- `ups_input_frequency` - Input frequency in Hz (gauge)
- `ups_temperature` - Temperature in Celsius (gauge)
- `ups_status{status}` - UPS status: 1=online, 0=battery (gauge)

### Grafana Dashboard Example

Import this JSON to Grafana:

```json
{
  "dashboard": {
    "title": "UPS Monitoring",
    "panels": [
      {
        "title": "Battery Level",
        "targets": [{
          "expr": "ups_battery_level"
        }]
      },
      {
        "title": "Input Voltage",
        "targets": [{
          "expr": "ups_input_voltage"
        }]
      }
    ]
  }
}
```

## 📡 MQTT Integration

The system can publish telemetry data to MQTT broker for integration with IoT platforms.

### Configuration

Enable MQTT in `config.yaml`:

```yaml
mqtt:
  enabled: true
  broker: mqtt.example.com
  port: 1883
  topic: ups/telemetry
  username: mqtt_user  # optional
  password: mqtt_password  # optional
```

### MQTT Message Format

Messages are published as JSON to the configured topic:

```json
{
  "input_voltage": 225.6,
  "output_voltage": 224.8,
  "battery_voltage": 13.6,
  "battery_level": 100,
  "load_percent": 14,
  "load_power": 138,
  "frequency": 50.1,
  "input_frequency": 50.1,
  "temperature": 33.0,
  "timestamp": "2024-01-15 14:30:25",
  "status": "online",
  "uptime": "02:15:30"
}
```

### Subscribe to MQTT

```bash
# Using mosquitto_sub
mosquitto_sub -h mqtt.example.com -t ups/telemetry -u mqtt_user -P mqtt_password

# Using MQTT Explorer or other clients
# Connect to broker and subscribe to topic: ups/telemetry
```

### Home Assistant Integration

Add to `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "UPS Battery Level"
      state_topic: "ups/telemetry"
      value_template: "{{ value_json.battery_level }}"
      unit_of_measurement: "%"
      device_class: battery
      
    - name: "UPS Input Voltage"
      state_topic: "ups/telemetry"
      value_template: "{{ value_json.input_voltage }}"
      unit_of_measurement: "V"
      device_class: voltage
      
    - name: "UPS Status"
      state_topic: "ups/telemetry"
      value_template: "{{ value_json.status }}"
      icon: "mdi:power"
```

## 🐳 Docker Usage

### Build Image

```bash
docker build -t ups-monitor .
```

### Run Container

#### Basic Usage

```bash
docker run -d --name ups-monitor \
  --device=/dev/ttyUSB0:/dev/ttyUSB0 \
  -p 8080:8080 \
  ups-monitor
```

#### With Configuration File

```bash
docker run -d --name ups-monitor \
  --device=/dev/ttyUSB0:/dev/ttyUSB0 \
  -p 8080:8080 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  ups-monitor python3 mustmon.py --config /app/config.yaml
```

#### With Volume Mounts

```bash
docker run -d --name ups-monitor \
  --device=/dev/ttyUSB0:/dev/ttyUSB0 \
  -p 8080:8080 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/logs:/var/log/ups \
  ups-monitor
```

#### With Environment Variables

```bash
docker run -d --name ups-monitor \
  --device=/dev/ttyUSB0:/dev/ttyUSB0 \
  -p 8080:8080 \
  -e UPS_SERIAL_PORT=/dev/ttyUSB0 \
  ups-monitor
```

### Docker Compose

```bash
# Create config from example
cp config.yaml.example config.yaml

# Edit configuration
nano config.yaml

# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**docker-compose.yml** includes:
- Automatic device mounting
- Volume mounts for config and logs
- Health checks
- Log rotation
- Auto-restart policy

## 🚨 Alert System

The daemon automatically detects and reports alarm conditions:

- 🔴 **Low input voltage** (< 180V)
- 🔴 **Low battery level** (< 20%)
- 🔴 **High temperature** (> 40°C)
- 🔴 **High load** (> 80%)

Alarms are:
- Displayed in the web interface
- Included in JSON API response
- Logged with WARNING level
- Can be sent via MQTT (if configured)

## 📝 Logging

### Configuration

Configure logging in `config.yaml`:

```yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: /tmp/ups_web_daemon.log
  console: true
```

### Log Locations

- **File**: `/tmp/ups_web_daemon.log` (default, configurable)
- **Console**: stdout (if enabled)

### View Logs

```bash
# Real-time log viewing
tail -f /tmp/ups_web_daemon.log

# Last 100 lines
tail -n 100 /tmp/ups_web_daemon.log

# Filter errors
grep ERROR /tmp/ups_web_daemon.log

# In Docker
docker logs -f ups-monitor
```

### Log Rotation

For production, use logrotate:

```bash
# Create logrotate config
sudo nano /etc/logrotate.d/ups-monitor

/tmp/ups_web_daemon.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 upsmonitor upsmonitor
}
```

## 🛠 Management Utilities

### Test Web Interface

```bash
# Test all endpoints
python3 test_web.py

# Test specific host and port
python3 test_web.py 192.168.1.100 8080
```

### Check Status

```bash
# Check if running
ps aux | grep mustmon

# Check web interface
curl http://localhost:8080/api/health

# Check Prometheus metrics
curl http://localhost:8080/metrics
```

## 🐛 Troubleshooting

### Connection Issues

**Error**: `❌ Connection error: [Errno 2] No such file or directory: '/dev/ttyUSB0'`

**Solutions**:
```bash
# Check available serial ports
ls -la /dev/ttyUSB* /dev/ttyACM*

# Check permissions
sudo chmod 666 /dev/ttyUSB0

# Add user to dialout group
sudo usermod -a -G dialout $USER

# Check USB devices
lsusb

# In Docker, ensure device is mounted
docker run --device=/dev/ttyUSB0:/dev/ttyUSB0 ...
```

### Web Server Issues

**Error**: `❌ Cannot connect to http://localhost:8080`

**Solutions**:
```bash
# Check if daemon is running
ps aux | grep mustmon

# Check port usage
netstat -tulpn | grep 8080
# or
ss -tulpn | grep 8080

# Check logs for errors
tail -f /tmp/ups_web_daemon.log

# Try different port
python3 mustmon.py /dev/ttyUSB0 --web-port 9000
```

### MQTT Connection Issues

**Error**: `❌ MQTT подключение неудачно`

**Solutions**:
```bash
# Test MQTT broker connectivity
mosquitto_pub -h mqtt.example.com -t test -m "test"

# Check MQTT credentials in config.yaml
# Verify broker address and port
# Check firewall rules
# Review MQTT logs in main log file
```

### Prometheus Metrics Not Available

**Solutions**:
```bash
# Verify metrics endpoint
curl http://localhost:8080/metrics

# Check Prometheus config
# Verify target is reachable
# Check Prometheus logs
```

### Data Issues

**Error**: `Failed to get telemetry`

**Solutions**:
- Check physical UPS connection
- Verify correct serial port is used
- Check serial port permissions
- Review logs for detailed error messages
- Try reconnecting UPS
- Verify UPS is powered on

## 📁 Project Structure

```
must-inverter/
├── mustmon.py              # Main daemon application
├── config.yaml.example     # Example configuration file
├── requirements.txt        # Python dependencies
├── test_web.py            # Web interface testing utility
├── Dockerfile             # Docker build configuration
├── docker-compose.yml     # Docker Compose configuration
├── .dockerignore          # Docker ignore patterns
└── README.md              # This documentation
```

## 📦 Dependencies

### Core Dependencies

- `pyserial==3.5` - Serial port communication
- `prometheus-client==0.17.1` - Prometheus metrics export
- `paho-mqtt==1.6.1` - MQTT client
- `PyYAML==6.0.1` - YAML configuration parsing

### Optional Dependencies

- `requests==2.31.0` - HTTP client (for testing)
- `ujson==5.8.0` - Fast JSON parsing
- `structlog==23.1.0` - Advanced logging
- `pydantic==2.4.2` - Configuration validation
- `python-dotenv==1.0.0` - Environment variable management

Install all dependencies:
```bash
pip3 install -r requirements.txt
```

## 🔒 Security Considerations

- The web server binds to `0.0.0.0` by default (accessible from network)
- Consider using a reverse proxy (nginx/traefik) for production
- Implement authentication if exposed to the internet
- Use HTTPS in production (via reverse proxy)
- Restrict MQTT credentials access (use secrets management)
- Regularly update dependencies for security patches
- Run as non-root user (implemented in Docker)

## 📈 Performance

- **Memory usage**: ~50-80MB
- **CPU usage**: Minimal (< 1% on modern hardware)
- **Network**: Light HTTP traffic (~1-2 KB per request)
- **Serial communication**: Non-blocking with timeouts
- **Polling interval**: Configurable (default 30 seconds)

## 🔄 API Rate Limits

- No built-in rate limiting
- Recommended: 1-2 requests per second maximum
- Web interface auto-refreshes every 10 seconds
- Prometheus scraping typically every 30-60 seconds

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

See [LICENSE](LICENSE) file for details.

## 📞 Support

If you encounter issues:

1. Check logs: `/tmp/ups_web_daemon.log` or `docker logs ups-monitor`
2. Verify UPS connection and serial port
3. Review configuration file syntax
4. Check port settings and permissions
5. Review troubleshooting section above
6. Open an issue on GitHub with logs and configuration (sanitized)

## 🙏 Acknowledgments

This system is designed to work with MUST EP20-1000-Pro UPS devices via serial port using a protocol based on analysis of original software traffic.

---

**Version**: 2.0  
**Last Updated**: 2024  
**Python Version**: 3.11+  
**Docker**: Multi-stage optimized build
