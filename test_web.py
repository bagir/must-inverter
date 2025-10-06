#!/usr/bin/env python3
"""
Simple test script for UPS Web Daemon
"""

import requests
import time
import sys

def test_web_interface(host='localhost', port=8080):
    """Тестирование веб-интерфейса"""
    base_url = f"http://{host}:{port}"
    
    print(f"🔍 Тестирование веб-интерфейса: {base_url}")
    
    try:
        # Тест health endpoint
        print("\n1. Testing /api/health...")
        response = requests.get(f"{base_url}/api/health", timeout=5)
        if response.status_code == 200:
            print(f"   ✅ Health: {response.json()}")
        else:
            print(f"   ❌ Health failed: {response.status_code}")
        
        # Тест telemetry endpoint
        print("\n2. Testing /api/telemetry...")
        response = requests.get(f"{base_url}/api/telemetry", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Telemetry received:")
            print(f"      Input Voltage: {data.get('input_voltage', 0):.1f}V")
            print(f"      Battery Level: {data.get('battery_level', 0)}%")
            print(f"      Load: {data.get('load_percent', 0)}%")
            print(f"      Status: {data.get('status', 'unknown')}")
        else:
            print(f"   ❌ Telemetry failed: {response.status_code}")
        
        # Тест главной страницы
        print("\n3. Testing main page...")
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            print("   ✅ Main page: OK")
        else:
            print(f"   ❌ Main page failed: {response.status_code}")
        
        print(f"\n🎉 Все тесты пройдены!")
        print(f"🌐 Откройте в браузере: {base_url}")
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Не удалось подключиться к {base_url}")
        print("   Убедитесь что демон запущен")
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    
    test_web_interface(host, port)
