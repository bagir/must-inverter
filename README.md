# MUST EP 20 1000 UPS Monitoring System. Replacement for Solar Power Monitor

A comprehensive UPS (Uninterruptible Power Supply) monitoring system with web interface and JSON API.

## 📋 Features

- 🔄 **Automatic polling** of UPS every 30 seconds
- 🌐 **Web interface** with beautiful data visualization
- 📊 **JSON API** for integration with other systems
- 🚨 **Alert system** for problem detection
- 📈 **Graphical battery level indicator**
- 🔧 **Automatic reconnection** on communication errors
- 📝 **Comprehensive logging** of all events

## 📊 Monitored Parameters

- ⚡ Input voltage
- 🔌 Output voltage
- 🔄 Frequency
- 🔋 Battery voltage
- 📈 Battery level (%)
- 💪 Load power (Watts)
- 📊 Load percentage
- 🌡️ Temperature

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install Python3 and pip (if not installed)
sudo apt update
sudo apt install python3 python3-pip

# Install required libraries
pip3 install pyserial
```

### 2. Run the System

```bash
# Main daemon with web interface
python3 mustmon.py /dev/ttyUSB0
```

### 3. Access Web Interface

After starting, open in your browser:
```
http://localhost:8080
```

## ⚙️ Configuration

### Command Line Parameters

```bash
# Basic startup (port 8080, interval 30 sec)
python3 mustmon.py /dev/ttyUSB0

# With custom web server port
python3 mustmon.py /dev/ttyUSB0 9000

# With custom port and polling interval
python3 mustmon.py /dev/ttyUSB0 8080 60
```

**Parameters:**
- `/dev/ttyUSB0` - UPS serial port
- `8080` - Web server port (default: 8080)
- `60` - Polling interval in seconds (default: 30)

### Running in Background

```bash
# Run daemon in background
nohup python3 mustmon.py /dev/ttyUSB0 > /dev/null 2>&1 &

# Check if running
ps aux | grep mustmon
```

## 🌐 Web Interface

### Main Page
- **URL**: `http://localhost:8080/`
- **Description**: Beautiful web interface with data cards
- **Auto-refresh**: Every 10 seconds

### JSON API

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

## 🛠 Management Utilities

### Daemon Manager

TO BE DONE

### Web Interface Testing

```bash
# Test all endpoints
python3 test_web.py

# Test specific host and port
python3 test_web.py 192.168.1.100 8080
```

## 🚨 Alert System

The daemon automatically detects and reports:

- 🔴 **Low input voltage** (< 180V)
- 🔴 **Low battery level** (< 20%)
- 🔴 **High temperature** (> 40°C)
- 🔴 **High load** (> 80%)

Alerts are displayed in the web interface and logged.

## 📊 Logging

All events are logged to:
```
/tmp/ups_web_daemon.log
```

**Example logs:**
```
2024-01-15 14:30:25 - INFO - Telemetry: Vin=225.6V, Vout=224.8V, Batt=13.6V, Load=14%
2024-01-15 14:30:55 - INFO - Telemetry: Vin=225.5V, Vout=224.7V, Batt=13.6V, Load=14%
2024-01-15 14:31:25 - WARNING - Alert: High temperature
```

View logs in real-time:
```bash
tail -f /tmp/ups_web_daemon.log
```

## 🔧 Integration

### Prometheus Integration Example

```python
#!/usr/bin/env python3
import requests
import time

def collect_ups_metrics():
    """Collect UPS metrics for Prometheus"""
    try:
        response = requests.get('http://localhost:8080/api/telemetry', timeout=5)
        data = response.json()
        
        metrics = []
        metrics.append(f'ups_input_voltage {data["input_voltage"]}')
        metrics.append(f'ups_battery_voltage {data["battery_voltage"]}')
        metrics.append(f'ups_battery_level {data["battery_level"]}')
        metrics.append(f'ups_load_percent {data["load_percent"]}')
        metrics.append(f'ups_temperature {data["temperature"]}')
        metrics.append(f'ups_status {{status="{data["status"]}"}} 1')
        
        return '\n'.join(metrics)
    except Exception as e:
        print(f"Error collecting UPS metrics: {e}")
        return ""
```

### Home Assistant Integration Example

```yaml
# configuration.yaml
sensor:
  - platform: rest
    name: "UPS Input Voltage"
    resource: http://localhost:8080/api/telemetry
    json_attributes_path: "$"
    value_template: "{{ value_json.input_voltage }}"
    unit_of_measurement: "V"
    
  - platform: rest
    name: "UPS Battery Level"
    resource: http://localhost:8080/api/telemetry
    value_template: "{{ value_json.battery_level }}"
    unit_of_measurement: "%"
```

### Grafana Dashboard

Use the JSON API to create dashboards in Grafana:

```json
{
  "datasource": "Prometheus",
  "targets": [
    {
      "expr": "ups_battery_level",
      "legendFormat": "Battery Level"
    }
  ]
}
```

## 🐛 Troubleshooting

### Connection Issues

**Error**: `❌ Connection error: [Errno 2] No such file or directory: '/dev/ttyUSB0'`

**Solution**:
```bash
# Check available ports
ls -la /dev/ttyUSB*

# Check permissions
sudo chmod 666 /dev/ttyUSB0

# Check USB devices
lsusb
```

### Web Server Issues

**Error**: `❌ Cannot connect to http://localhost:8080`

**Solution**:
```bash
# Check daemon status
python3 ups_web_manager.py status

# Check port usage
netstat -tulpn | grep 8080

# Restart daemon
python3 ups_web_manager.py restart /dev/ttyUSB0
```

### Data Issues

**Error**: `Failed to get telemetry`

**Solution**:
- Check physical UPS connection
- Verify correct port is used
- Check logs for detailed information

## 📁 File Structure

```
must-inverter/
├── mustmon.py    # Main daemon with web interface
├── test_web.py               # Web interface testing
└── README.md                 # This documentation
```

## 🔒 Security Considerations

- The web server binds to `0.0.0.0` by default
- Consider using a reverse proxy (nginx) for production
- Implement authentication if exposed to the internet
- Regularly update the system and dependencies

## 📈 Performance

- **Memory usage**: ~50MB
- **CPU usage**: Minimal (single-threaded)
- **Network**: Light HTTP traffic
- **Storage**: Log rotation recommended for long-term operation

## 🔄 API Rate Limits

- No built-in rate limiting
- Recommended: 1 request per second maximum
- Web interface auto-refreshes every 10 seconds

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📞 Support

If you encounter issues:
1. Check logs: `/tmp/ups_web_daemon.log`
2. Verify UPS connection
3. Check port settings and permissions

---

**Note**: This system is designed to work with UPS devices via serial port using a protocol based on analysis of original software traffic.
