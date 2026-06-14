# Virtual Instrument Port Assignments

Each virtual instrument uses two ports: SCPI TCP and HTTP/WebSocket.

| Instrument | SCPI Port | HTTP Port | Status |
|------------|-----------|-----------|--------|
| numeric-display | 5025 | 8000 | ✅ Complete |
| analog-meter | 5027 | 8003 | ✅ Complete |
| led | 5028 | 8004 | ✅ Complete |
| bar-graph | 5026 | 8002 | ✅ Complete |
| line-chart | 5029 | 8005 | TODO |
| xy-plot | 5030 | 8006 | TODO |
| text-lcd | 5031 | 8007 | TODO |
| waterfall | 5032 | 8008 | TODO |
| compass | 5033 | 8009 | TODO |
| gauge-cluster | 5034 | 8010 | TODO |

## Testing Multiple Instruments

To run multiple instruments simultaneously, start each in its own terminal or as a background process:

```bash
# Start numeric display
cd ~/Dropbox/build/rf-bench/virtual/numeric-display/backend && python3 server.py &

# Start bar graph
cd ~/Dropbox/build/rf-bench/virtual/bar-graph/backend && python3 server.py &

# etc...
```

Access via:
- Numeric Display: http://localhost:8000
- Bar Graph: http://localhost:8002
- Analog Meter: http://localhost:8003
- etc...
