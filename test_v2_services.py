"""
Unit & integration verification script for MonaMiner v2.0.0 services:
1. ProfitCalculator math check
2. GpuHardwareController NVML ctypes bind check
3. IdleTracker Windows API GetLastInputInfo check
4. WebMonitoringServer HTTP GET / and /api/status check
5. OpenCL Multi-GPU enumeration check
"""
import sys
import time
import urllib.request
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from app.services import (
    ProfitCalculator, GpuHardwareController,
    IdleTracker, WebMonitoringServer
)
from app.miner.opencl_backend import OpenCLBackend

def test_profit_calculator():
    calc = ProfitCalculator(electricity_rate_yen=31.0, mona_jpy_price=45.0)
    res = calc.calculate(hashrate_mhs=100.0, power_watts=200.0)
    assert res["watt_per_mh"] == 2.0
    assert res["hourly_cost_yen"] > 0
    assert res["daily_cost_yen"] > 0
    assert res["est_daily_mona"] > 0
    print(f"✓ ProfitCalculator PASS: 100MH/s @ 200W -> ¥{res['daily_cost_yen']}/day, est {res['est_daily_mona']} MONA")

def test_gpu_hardware_controller():
    ctrl = GpuHardwareController()
    print(f"✓ GpuHardwareController: Available={ctrl.is_available}, Count={ctrl.device_count}")
    if ctrl.is_available:
        info = ctrl.get_device_info(0)
        print(f"  GPU #0 Telemetry: Name='{info.get('name')}', Temp={info.get('temp_c')}C, Fan={info.get('fan_percent')}%, Power={info.get('power_w')}W")

def test_idle_tracker():
    tracker = IdleTracker()
    idle_sec = tracker.get_idle_seconds()
    assert idle_sec >= 0.0
    print(f"✓ IdleTracker PASS: Current idle seconds = {idle_sec:.2f}s")

def test_opencl_devices():
    devs = OpenCLBackend.get_all_gpu_devices()
    print(f"✓ OpenCL Multi-GPU Discovery PASS: Found {len(devs)} device(s)")
    for d in devs:
        print(f"  - Device #{d['global_index']}: {d['name']} ({d['platform_name']})")

def test_web_server():
    server = WebMonitoringServer(port=8899)
    status_mock = {
        "is_mining": True,
        "hashrate_mhs": 185.5,
        "power_w": 220.0,
        "watt_per_mh": 1.186,
        "temp_c": 58,
        "fan_percent": 45,
        "accepted_shares": 12,
        "rejected_shares": 0,
        "hourly_cost_yen": 6.8,
        "daily_cost_yen": 163.7,
        "uptime_str": "01:23:45",
        "recent_logs": ["Log line 1", "Log line 2"]
    }
    server.start(
        get_status_fn=lambda: status_mock,
        start_fn=lambda: None,
        stop_fn=lambda: None
    )
    time.sleep(0.3)
    try:
        # Test HTML page
        req = urllib.request.Request("http://127.0.0.1:8899/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8")
            assert "MonaMinerRTX Web Dashboard" in html
        
        # Test API JSON
        req_api = urllib.request.Request("http://127.0.0.1:8899/api/status")
        with urllib.request.urlopen(req_api, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["hashrate_mhs"] == 185.5
            assert data["is_mining"] is True

        print("✓ WebMonitoringServer PASS: HTML dashboard & /api/status verified successfully")
    finally:
        server.stop()
        time.sleep(0.2)

if __name__ == "__main__":
    print("=== Testing MonaMiner v2.0.0 Services ===")
    test_profit_calculator()
    test_gpu_hardware_controller()
    test_idle_tracker()
    test_opencl_devices()
    test_web_server()
    print("=== ALL v2.0.0 SERVICE TESTS PASSED! ===")
