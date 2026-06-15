#!/usr/bin/env python3
"""
Remote HF Station Control — Flask Web Server

Integrates:
- IC-7300 radio control via Hamlib rigctld (rf_bench.icom.IC7300)
- ESP32 SCPI antenna rotator (scpi-rotator)
- ESP32 SCPI PTT controller (scpi-ptt)
- ESP32 SCPI SWR meter (scpi-swr)

Web UI provides frequency/mode control, antenna aiming, PTT, and
real-time SWR monitoring via WebSocket.

Usage:
    # Start rigctld first:
    rigctld -m 3073 -r /dev/ttyUSB0 -s 115200

    # Then run this server:
    python3 remote_station.py

    # Access web UI at:
    http://localhost:5000
"""

import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify
from flask_sock import Sock
import pyvisa

from rf_bench.icom import IC7300
from rf_bench import connect


app = Flask(__name__)
sock = Sock(app)

# Global state
radio = None
rotator = None
ptt = None
swr_meter = None
db_path = Path(__file__).parent / "qso_log.db"


def init_database():
    """Create QSO log database if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS qsos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            frequency_khz INTEGER NOT NULL,
            mode TEXT NOT NULL,
            swr REAL,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_qso(freq_khz, mode, swr=None, notes=""):
    """Log a QSO to the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO qsos (timestamp, frequency_khz, mode, swr, notes) VALUES (?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), freq_khz, mode, swr, notes)
    )
    conn.commit()
    conn.close()


def connect_instruments(rigctld_host, rigctld_port, rotator_ip, ptt_ip, swr_ip):
    """Connect to IC-7300 and three ESP32 SCPI controllers."""
    global radio, rotator, ptt, swr_meter

    # Connect to IC-7300 via Hamlib rigctld
    radio = IC7300(host=rigctld_host, port=rigctld_port)

    # Connect to ESP32 SCPI devices
    rm = pyvisa.ResourceManager('@py')
    rotator = rm.open_resource(f'TCPIP0::{rotator_ip}::5025::SOCKET')
    ptt = rm.open_resource(f'TCPIP0::{ptt_ip}::5025::SOCKET')
    swr_meter = rm.open_resource(f'TCPIP0::{swr_ip}::5025::SOCKET')

    # Set read terminators
    for inst in [rotator, ptt, swr_meter]:
        inst.read_termination = '\n'
        inst.write_termination = '\n'


# HTML template for web UI
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Remote HF Station</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a1a;
            color: #e0e0e0;
        }
        h1, h2 {
            color: #4CAF50;
        }
        .panel {
            background: #2d2d2d;
            border: 2px solid #444;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .control-group {
            margin-bottom: 15px;
        }
        label {
            display: inline-block;
            width: 120px;
            font-weight: bold;
        }
        input[type="number"], input[type="text"], select {
            width: 200px;
            padding: 8px;
            background: #1a1a1a;
            border: 1px solid #555;
            border-radius: 4px;
            color: #e0e0e0;
        }
        input[type="range"] {
            width: 300px;
            vertical-align: middle;
        }
        button {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            margin-right: 10px;
        }
        button:hover {
            background: #45a049;
        }
        button:active {
            background: #3d8b40;
        }
        .ptt-button {
            background: #f44336;
            font-size: 20px;
            padding: 15px 30px;
        }
        .ptt-button:hover {
            background: #da190b;
        }
        .ptt-button.active {
            background: #b71c1c;
        }
        .swr-meter {
            font-size: 48px;
            font-weight: bold;
            text-align: center;
            padding: 20px;
            background: #1a1a1a;
            border-radius: 8px;
            margin-top: 10px;
        }
        .swr-good { color: #4CAF50; }
        .swr-warn { color: #ff9800; }
        .swr-bad { color: #f44336; }
        .status {
            background: #1a1a1a;
            padding: 10px;
            border-radius: 4px;
            font-family: monospace;
            margin-top: 10px;
        }
        .slider-value {
            display: inline-block;
            width: 60px;
            text-align: right;
            font-weight: bold;
            color: #4CAF50;
        }
    </style>
</head>
<body>
    <h1>🛰️ Remote HF Station Control</h1>

    <div class="panel">
        <h2>📻 Radio Control (IC-7300)</h2>
        <div class="control-group">
            <label>Frequency (kHz):</label>
            <input type="number" id="freq" value="14074" step="1">
            <button onclick="setFrequency()">Set</button>
        </div>
        <div class="control-group">
            <label>Mode:</label>
            <select id="mode">
                <option value="USB">USB</option>
                <option value="LSB">LSB</option>
                <option value="CW">CW</option>
                <option value="RTTY">RTTY</option>
                <option value="AM">AM</option>
                <option value="FM">FM</option>
            </select>
            <button onclick="setMode()">Set</button>
        </div>
        <div class="control-group">
            <button onclick="getRadioStatus()">Get Status</button>
        </div>
        <div class="status" id="radio-status">Status: Not connected</div>
    </div>

    <div class="panel">
        <h2>🎯 Antenna Rotator</h2>
        <div class="control-group">
            <label>Azimuth:</label>
            <input type="range" id="azimuth" min="0" max="360" value="0" oninput="updateAzimuthDisplay()">
            <span class="slider-value" id="azimuth-display">0°</span>
            <button onclick="setAzimuth()">Set</button>
        </div>
        <div class="control-group">
            <label>Elevation:</label>
            <input type="range" id="elevation" min="0" max="90" value="0" oninput="updateElevationDisplay()">
            <span class="slider-value" id="elevation-display">0°</span>
            <button onclick="setElevation()">Set</button>
        </div>
        <div class="control-group">
            <button onclick="getRotatorPosition()">Get Position</button>
            <button onclick="aimAntenna()">Aim Antenna</button>
        </div>
        <div class="status" id="rotator-status">Status: Not connected</div>
    </div>

    <div class="panel">
        <h2>🔴 PTT Control</h2>
        <button class="ptt-button" id="ptt-button"
                onmousedown="setPTT(true)"
                onmouseup="setPTT(false)"
                ontouchstart="setPTT(true)"
                ontouchend="setPTT(false)">
            TRANSMIT
        </button>
        <div class="status" id="ptt-status">PTT: OFF</div>
    </div>

    <div class="panel">
        <h2>📊 SWR Meter</h2>
        <div class="swr-meter" id="swr-display">
            <span class="swr-good">--</span>
        </div>
        <div class="status">WebSocket: <span id="ws-status">Connecting...</span></div>
    </div>

    <div class="panel">
        <h2>📝 Quick QSO Log</h2>
        <div class="control-group">
            <label>Notes:</label>
            <input type="text" id="qso-notes" placeholder="Callsign, report, etc.">
            <button onclick="logQSO()">Log QSO</button>
        </div>
        <div class="status" id="log-status">Ready to log</div>
    </div>

    <script>
        let ws = null;
        let currentSWR = null;

        // WebSocket for real-time SWR monitoring
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + window.location.host + '/ws/swr');

            ws.onopen = () => {
                document.getElementById('ws-status').textContent = 'Connected';
                document.getElementById('ws-status').style.color = '#4CAF50';
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                currentSWR = data.swr;
                updateSWRDisplay(data.swr);
            };

            ws.onerror = () => {
                document.getElementById('ws-status').textContent = 'Error';
                document.getElementById('ws-status').style.color = '#f44336';
            };

            ws.onclose = () => {
                document.getElementById('ws-status').textContent = 'Disconnected';
                document.getElementById('ws-status').style.color = '#ff9800';
                setTimeout(connectWebSocket, 3000);
            };
        }

        function updateSWRDisplay(swr) {
            const display = document.getElementById('swr-display');
            let className = 'swr-good';
            if (swr > 2.0) className = 'swr-warn';
            if (swr > 3.0) className = 'swr-bad';
            display.innerHTML = `<span class="${className}">${swr.toFixed(2)}</span>`;
        }

        function updateAzimuthDisplay() {
            const value = document.getElementById('azimuth').value;
            document.getElementById('azimuth-display').textContent = value + '°';
        }

        function updateElevationDisplay() {
            const value = document.getElementById('elevation').value;
            document.getElementById('elevation-display').textContent = value + '°';
        }

        async function apiCall(endpoint, method = 'GET', body = null) {
            const options = { method };
            if (body) {
                options.headers = { 'Content-Type': 'application/json' };
                options.body = JSON.stringify(body);
            }
            const response = await fetch(endpoint, options);
            return response.json();
        }

        async function setFrequency() {
            const freq = parseInt(document.getElementById('freq').value);
            const result = await apiCall('/api/radio/frequency', 'POST', { frequency_khz: freq });
            document.getElementById('radio-status').textContent =
                result.success ? `Frequency set to ${freq} kHz` : `Error: ${result.error}`;
        }

        async function setMode() {
            const mode = document.getElementById('mode').value;
            const result = await apiCall('/api/radio/mode', 'POST', { mode: mode });
            document.getElementById('radio-status').textContent =
                result.success ? `Mode set to ${mode}` : `Error: ${result.error}`;
        }

        async function getRadioStatus() {
            const result = await apiCall('/api/radio/status');
            if (result.success) {
                document.getElementById('radio-status').textContent =
                    `Freq: ${result.frequency_khz} kHz | Mode: ${result.mode}`;
                document.getElementById('freq').value = result.frequency_khz;
                document.getElementById('mode').value = result.mode;
            }
        }

        async function setAzimuth() {
            const az = parseInt(document.getElementById('azimuth').value);
            const result = await apiCall('/api/rotator/azimuth', 'POST', { azimuth: az });
            document.getElementById('rotator-status').textContent =
                result.success ? `Azimuth set to ${az}°` : `Error: ${result.error}`;
        }

        async function setElevation() {
            const el = parseInt(document.getElementById('elevation').value);
            const result = await apiCall('/api/rotator/elevation', 'POST', { elevation: el });
            document.getElementById('rotator-status').textContent =
                result.success ? `Elevation set to ${el}°` : `Error: ${result.error}`;
        }

        async function aimAntenna() {
            const az = parseInt(document.getElementById('azimuth').value);
            const el = parseInt(document.getElementById('elevation').value);
            const result = await apiCall('/api/rotator/aim', 'POST', { azimuth: az, elevation: el });
            document.getElementById('rotator-status').textContent =
                result.success ? `Aiming to Az:${az}° El:${el}°` : `Error: ${result.error}`;
        }

        async function getRotatorPosition() {
            const result = await apiCall('/api/rotator/position');
            if (result.success) {
                document.getElementById('rotator-status').textContent =
                    `Az: ${result.azimuth}° | El: ${result.elevation}°`;
                document.getElementById('azimuth').value = result.azimuth;
                document.getElementById('elevation').value = result.elevation;
                updateAzimuthDisplay();
                updateElevationDisplay();
            }
        }

        async function setPTT(state) {
            const button = document.getElementById('ptt-button');
            button.classList.toggle('active', state);
            const result = await apiCall('/api/ptt', 'POST', { state: state });
            document.getElementById('ptt-status').textContent =
                result.success ? `PTT: ${state ? 'ON' : 'OFF'}` : `Error: ${result.error}`;
        }

        async function logQSO() {
            const notes = document.getElementById('qso-notes').value;
            const freq = parseInt(document.getElementById('freq').value);
            const mode = document.getElementById('mode').value;
            const result = await apiCall('/api/log/qso', 'POST', {
                frequency_khz: freq,
                mode: mode,
                swr: currentSWR,
                notes: notes
            });
            document.getElementById('log-status').textContent =
                result.success ? 'QSO logged!' : `Error: ${result.error}`;
            document.getElementById('qso-notes').value = '';
        }

        // Initialize on page load
        connectWebSocket();
        getRadioStatus();
        getRotatorPosition();
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Serve the web UI."""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/radio/frequency', methods=['POST'])
def set_radio_frequency():
    """Set radio frequency."""
    try:
        data = request.json
        freq_khz = data['frequency_khz']
        radio.set_frequency(freq_khz)
        return jsonify({'success': True, 'frequency_khz': freq_khz})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/radio/mode', methods=['POST'])
def set_radio_mode():
    """Set radio mode."""
    try:
        data = request.json
        mode = data['mode']
        radio.set_mode(mode)
        return jsonify({'success': True, 'mode': mode})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/radio/status', methods=['GET'])
def get_radio_status():
    """Get current radio frequency and mode."""
    try:
        freq_khz = radio.get_frequency()
        mode = radio.get_mode()
        return jsonify({'success': True, 'frequency_khz': freq_khz, 'mode': mode})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/rotator/azimuth', methods=['POST'])
def set_rotator_azimuth():
    """Set rotator azimuth."""
    try:
        data = request.json
        az = data['azimuth']
        rotator.write(f'SOUR:AZ {az}')
        return jsonify({'success': True, 'azimuth': az})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/rotator/elevation', methods=['POST'])
def set_rotator_elevation():
    """Set rotator elevation."""
    try:
        data = request.json
        el = data['elevation']
        rotator.write(f'SOUR:EL {el}')
        return jsonify({'success': True, 'elevation': el})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/rotator/aim', methods=['POST'])
def aim_rotator():
    """Set both azimuth and elevation."""
    try:
        data = request.json
        az = data['azimuth']
        el = data['elevation']
        rotator.write(f'SOUR:AZ {az}')
        rotator.write(f'SOUR:EL {el}')
        return jsonify({'success': True, 'azimuth': az, 'elevation': el})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/rotator/position', methods=['GET'])
def get_rotator_position():
    """Get current rotator position."""
    try:
        az = float(rotator.query('SOUR:AZ?'))
        el = float(rotator.query('SOUR:EL?'))
        return jsonify({'success': True, 'azimuth': az, 'elevation': el})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/ptt', methods=['POST'])
def set_ptt():
    """Control PTT state."""
    try:
        data = request.json
        state = data['state']
        ptt.write(f'OUTP:STAT {1 if state else 0}')
        return jsonify({'success': True, 'state': state})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/log/qso', methods=['POST'])
def log_qso_endpoint():
    """Log a QSO."""
    try:
        data = request.json
        log_qso(
            data['frequency_khz'],
            data['mode'],
            data.get('swr'),
            data.get('notes', '')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@sock.route('/ws/swr')
def swr_websocket(ws):
    """WebSocket endpoint for real-time SWR monitoring."""
    try:
        while True:
            swr = float(swr_meter.query('MEAS:SWR?'))
            ws.send(json.dumps({'swr': swr}))
            time.sleep(0.5)  # Update twice per second
    except Exception as e:
        print(f"WebSocket error: {e}")


def main():
    parser = argparse.ArgumentParser(description='Remote HF Station Control Server')
    parser.add_argument('--rigctld-host', default='localhost',
                        help='rigctld hostname (default: localhost)')
    parser.add_argument('--rigctld-port', type=int, default=4532,
                        help='rigctld port (default: 4532)')
    parser.add_argument('--rotator-ip', required=True,
                        help='ESP32 rotator IP address')
    parser.add_argument('--ptt-ip', required=True,
                        help='ESP32 PTT controller IP address')
    parser.add_argument('--swr-ip', required=True,
                        help='ESP32 SWR meter IP address')
    parser.add_argument('--host', default='0.0.0.0',
                        help='Flask server bind address (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000,
                        help='Flask server port (default: 5000)')
    args = parser.parse_args()

    print("Connecting to instruments...")
    connect_instruments(
        args.rigctld_host,
        args.rigctld_port,
        args.rotator_ip,
        args.ptt_ip,
        args.swr_ip
    )
    print("✓ All instruments connected")

    print("Initializing database...")
    init_database()
    print("✓ Database ready")

    print(f"\n🛰️  Remote HF Station Control Server")
    print(f"Web UI: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == '__main__':
    main()
