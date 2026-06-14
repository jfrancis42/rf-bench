# Virtual Instrument Port Assignments

Each virtual instrument uses two ports: SCPI TCP and HTTP/WebSocket.

Port ranges:
- SCPI TCP: 5000-5009 (one per instrument)
- HTTP/WebSocket: 8000-8009 (one per instrument)

| Instrument | SCPI Port | HTTP/WS Port | Status |
|------------|-----------|--------------|--------|
| numeric-display | 5000 | 8000 | ✅ Complete |
| bar-graph | 5001 | 8001 | ✅ Complete |
| analog-meter | 5002 | 8002 | ✅ Complete |
| led | 5003 | 8003 | ✅ Complete |
| line-chart | 5004 | 8004 | ✅ Complete |
| xy-plot | 5005 | 8005 | ✅ Complete |
| text-lcd | 5006 | 8006 | ✅ Complete |
| waterfall | 5007 | 8007 | ✅ Complete |
| compass | 5008 | 8008 | ✅ Complete |
| gauge-cluster | 5009 | 8009 | ✅ Complete |

## Testing Multiple Instruments

To run multiple instruments simultaneously, start each in its own terminal or as a background process:

```bash
# Start numeric display
cd ~/Dropbox/build/rf-bench/virtual/numeric-display/backend && python3 server.py &

# Start bar graph
cd ~/Dropbox/build/rf-bench/virtual/bar-graph/backend && python3 server.py &

# Start analog meter
cd ~/Dropbox/build/rf-bench/virtual/analog-meter/backend && python3 server.py &

# etc...
```

Access via:
- Numeric Display: http://localhost:8000
- Bar Graph: http://localhost:8001
- Analog Meter: http://localhost:8002
- LED: http://localhost:8003
- Line Chart: http://localhost:8004
- XY Plot: http://localhost:8005
- Text LCD: http://localhost:8006
- Waterfall: http://localhost:8007
- Compass: http://localhost:8008
- Gauge Cluster: http://localhost:8009
