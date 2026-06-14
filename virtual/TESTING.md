# Virtual Instruments - MQTT Testing Guide

All three Phase 1 virtual instruments now support both SCPI and MQTT control.

## MQTT Broker

- **Host:** 10.1.0.20 (dmz)
- **Port:** 1883
- **Service:** Mosquitto 2.0.18

## Instruments Ready for Testing

### 1. Analog Meter
- **Status:** ✅ Tested and working
- **SCPI Port:** 5025
- **Web UI:** http://10.1.0.10:8000
- **MQTT Topic:** bench/meter/value
- **Example:** `mosquitto_pub -h 10.1.0.20 -t bench/meter/value -m "-75"`

### 2. Numeric Display
- **Status:** 🔨 Code complete, needs testing
- **SCPI Port:** 5025
- **Web UI:** http://10.1.0.10:8000
- **MQTT Topic:** bench/display/value
- **Example:** `mosquitto_pub -h 10.1.0.20 -t bench/display/value -m "14.257"`

### 3. LED Indicator
- **Status:** 🔨 Code complete, needs testing
- **SCPI Port:** 5025
- **Web UI:** http://10.1.0.10:8000
- **MQTT Topic:** bench/led/state
- **Example:** `mosquitto_pub -h 10.1.0.20 -t bench/led/state -m "1"`

## Testing Sequence

For each instrument:

1. **Start server on mother (10.1.0.10):**
   ```bash
   cd ~/Dropbox/build/rf-bench/virtual/<instrument>/backend
   python3 server.py
   ```

2. **Open web UI:** http://localhost:8000 (or http://10.1.0.10:8000 from remote)

3. **Configure MQTT via SCPI:**
   ```bash
   python3 << 'EOF'
   import socket
   s = socket.socket()
   s.connect(('10.1.0.10', 5025))
   s.sendall(b'MQTT:CONF 10.1.0.20,<topic>\n')
   s.close()
   EOF
   ```

4. **Test SCPI control** (from minime or any host)

5. **Test MQTT control** (from minime or any host)

## Known Working Configuration (Analog Meter)

Scale: -120 to -30 dBm with colored zones:
```bash
echo "CONF:MIN -120" | nc 10.1.0.10 5025
echo "CONF:MAX -30" | nc 10.1.0.10 5025
echo "CONF:UNIT dBm" | nc 10.1.0.10 5025
echo "CONF:ZONE 1,-120,-90,#226644" | nc 10.1.0.10 5025
echo "CONF:ZONE 2,-90,-60,#886600" | nc 10.1.0.10 5025
echo "CONF:ZONE 3,-60,-30,#882222" | nc 10.1.0.10 5025
echo "MQTT:CONF 10.1.0.20,bench/meter/value" | nc 10.1.0.10 5025
```

Then test with:
```bash
mosquitto_pub -h 10.1.0.20 -t bench/meter/value -m "-75"
```

Needle swings with realistic spring-damper physics!
