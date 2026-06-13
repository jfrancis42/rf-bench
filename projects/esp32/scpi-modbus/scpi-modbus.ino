/*
 * SCPI Modbus RTU Bridge for ESP32
 *
 * Network-accessible Modbus RTU master bridge that provides read/write access
 * to Modbus slave devices via SCPI commands over TCP/IP on port 5025.
 *
 * Hardware connections:
 *   MAX485/MAX3485 RS-485 transceiver:
 *     ESP32 GPIO 17 (UART2 TX) → DI (data in)
 *     ESP32 GPIO 16 (UART2 RX) → RO (receiver output)
 *     ESP32 GPIO 4            → DE and RE tied together (driver enable, active high)
 *     MAX485 A, B             → RS-485 bus A, B
 *     ESP32 GND, 3.3V         → MAX485 GND, VCC
 *
 * Modbus RTU standard baud rates: 9600, 19200, 38400, 115200 (default: 9600)
 * Modbus slave addresses: 1-247 (0 is broadcast, 248-255 reserved)
 *
 * Common Modbus devices:
 *   - Industrial PLCs (Schneider, Siemens, Allen-Bradley)
 *   - Energy meters (Carlo Gavazzi, Schneider PM series)
 *   - Temperature controllers (Omega, Omron E5CC)
 *   - Motor drives / VFDs (ABB, Danfoss, Yaskawa)
 *   - Building automation (HVAC controllers, lighting)
 *   - Solar inverters (Fronius, SMA)
 *   - Power supplies (programmable DC/AC sources)
 *   - Environmental sensors (temp, humidity, pressure)
 */

#include <WiFi.h>
#include <ModbusMaster.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// UART2 pins for Modbus RTU
const int uart_tx_pin = 17;  // GPIO 17 → MAX485 DI
const int uart_rx_pin = 16;  // GPIO 16 → MAX485 RO
const int de_re_pin = 4;     // GPIO 4  → MAX485 DE/RE (driver enable)

// Modbus configuration
uint32_t modbus_baud = 9600;       // default baud rate
uint8_t modbus_slave_addr = 1;     // default slave address

// ModbusMaster object (uses UART2)
ModbusMaster modbus;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// Modbus response buffer (holding registers can return up to 125 words = 250 bytes)
uint16_t modbus_response[125];

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Modbus RTU Bridge");
  Serial.println("======================");

  // Initialize DE/RE control pin (LOW = receive, HIGH = transmit)
  pinMode(de_re_pin, OUTPUT);
  digitalWrite(de_re_pin, LOW);

  // Initialize UART2 for Modbus RTU
  Serial2.begin(modbus_baud, SERIAL_8N1, uart_rx_pin, uart_tx_pin);
  Serial.printf("UART2 initialized: TX=%d, RX=%d, baud=%d\n",
                uart_tx_pin, uart_rx_pin, modbus_baud);

  // Initialize Modbus master (ModbusMaster library uses Serial2)
  modbus.begin(modbus_slave_addr, Serial2);

  // Set pre/post-transmission callbacks for DE/RE control
  modbus.preTransmission(preTransmission);
  modbus.postTransmission(postTransmission);

  Serial.printf("Modbus initialized: slave_addr=%d, DE/RE pin=%d\n",
                modbus_slave_addr, de_re_pin);

  // Connect to WiFi
  Serial.printf("Connecting to %s", ssid);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println(" connected!");
  Serial.printf("IP address: %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("SCPI port: %d\n", scpi_port);
  Serial.println("\nReady for SCPI commands");

  // Start SCPI server
  server.begin();
}

void loop() {
  // Handle new client connections
  if (!client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("Client connected");
      cmd_index = 0;
      memset(cmd_buffer, 0, sizeof(cmd_buffer));
    }
  }

  // Process data from connected client
  if (client && client.connected()) {
    while (client.available()) {
      char c = client.read();

      // Handle command termination (newline or semicolon)
      if (c == '\n' || c == '\r' || c == ';') {
        if (cmd_index > 0) {
          cmd_buffer[cmd_index] = '\0';
          process_scpi_command(cmd_buffer);
          cmd_index = 0;
          memset(cmd_buffer, 0, sizeof(cmd_buffer));
        }
      }
      // Add character to buffer
      else if (cmd_index < sizeof(cmd_buffer) - 1) {
        cmd_buffer[cmd_index++] = c;
      }
      // Buffer overflow - reset
      else {
        Serial.println("Command buffer overflow!");
        cmd_index = 0;
        memset(cmd_buffer, 0, sizeof(cmd_buffer));
        send_response("ERROR: Command too long\n");
      }
    }
  }
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// ModbusMaster pre-transmission callback (enable driver)
void preTransmission() {
  digitalWrite(de_re_pin, HIGH);  // Enable RS-485 driver
}

// ModbusMaster post-transmission callback (disable driver)
void postTransmission() {
  digitalWrite(de_re_pin, LOW);   // Disable RS-485 driver (back to receive mode)
}

// Read holding registers (function code 0x03)
void read_holding_registers(uint16_t reg, uint16_t count) {
  if (count > 125) {
    send_response("ERROR: Count out of range (max 125)\n");
    return;
  }

  uint8_t result = modbus.readHoldingRegisters(reg, count);

  if (result == modbus.ku8MBSuccess) {
    // Build CSV response
    char buf[512];
    int offset = 0;
    for (uint16_t i = 0; i < count; i++) {
      offset += snprintf(buf + offset, sizeof(buf) - offset, "%u", modbus.getResponseBuffer(i));
      if (i < count - 1) {
        buf[offset++] = ',';
      }
    }
    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  } else {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: Modbus error 0x%02X\n", result);
    send_response(buf);
  }
}

// Read input registers (function code 0x04)
void read_input_registers(uint16_t reg, uint16_t count) {
  if (count > 125) {
    send_response("ERROR: Count out of range (max 125)\n");
    return;
  }

  uint8_t result = modbus.readInputRegisters(reg, count);

  if (result == modbus.ku8MBSuccess) {
    // Build CSV response
    char buf[512];
    int offset = 0;
    for (uint16_t i = 0; i < count; i++) {
      offset += snprintf(buf + offset, sizeof(buf) - offset, "%u", modbus.getResponseBuffer(i));
      if (i < count - 1) {
        buf[offset++] = ',';
      }
    }
    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  } else {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: Modbus error 0x%02X\n", result);
    send_response(buf);
  }
}

// Write single holding register (function code 0x06)
void write_holding_register(uint16_t reg, uint16_t value) {
  uint8_t result = modbus.writeSingleRegister(reg, value);

  if (result == modbus.ku8MBSuccess) {
    send_response("OK\n");
  } else {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: Modbus error 0x%02X\n", result);
    send_response(buf);
  }
}

// Write single coil (function code 0x05)
void write_coil(uint16_t addr, bool value) {
  uint8_t result = modbus.writeSingleCoil(addr, value);

  if (result == modbus.ku8MBSuccess) {
    send_response("OK\n");
  } else {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: Modbus error 0x%02X\n", result);
    send_response(buf);
  }
}

// Process SCPI command
void process_scpi_command(char* cmd) {
  // Convert to uppercase for case-insensitive matching
  for (int i = 0; cmd[i]; i++) {
    cmd[i] = toupper(cmd[i]);
  }

  // Trim leading/trailing whitespace
  while (*cmd == ' ' || *cmd == '\t') cmd++;
  int len = strlen(cmd);
  while (len > 0 && (cmd[len-1] == ' ' || cmd[len-1] == '\t')) {
    cmd[--len] = '\0';
  }

  Serial.printf("SCPI: %s\n", cmd);

  // *IDN? - Identification query
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-Modbus,1.0,2026\n");
  }

  // *RST - Reset (resets to default baud and slave address)
  else if (strcmp(cmd, "*RST") == 0) {
    modbus_baud = 9600;
    modbus_slave_addr = 1;
    Serial2.end();
    Serial2.begin(modbus_baud, SERIAL_8N1, uart_rx_pin, uart_tx_pin);
    modbus.begin(modbus_slave_addr, Serial2);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // MODB:BAUD,<rate> - Set baud rate
  else if (strncmp(cmd, "MODB:BAUD", 9) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      uint32_t baud;
      if (sscanf(comma + 1, "%u", &baud) == 1) {
        if (baud == 9600 || baud == 19200 || baud == 38400 || baud == 115200) {
          modbus_baud = baud;
          Serial2.end();
          Serial2.begin(modbus_baud, SERIAL_8N1, uart_rx_pin, uart_tx_pin);
          modbus.begin(modbus_slave_addr, Serial2);
          send_response("OK\n");
        } else {
          send_response("ERROR: Baud rate must be 9600, 19200, 38400, or 115200\n");
        }
      } else {
        send_response("ERROR: Invalid baud rate\n");
      }
    } else {
      send_response("ERROR: Missing baud rate parameter\n");
    }
  }

  // MODB:BAUD? - Query baud rate
  else if (strcmp(cmd, "MODB:BAUD?") == 0) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%u\n", modbus_baud);
    send_response(buf);
  }

  // MODB:ADDR,<1-247> - Set target slave address
  else if (strncmp(cmd, "MODB:ADDR", 9) == 0 || strncmp(cmd, "MODB:ADDRESS", 12) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      uint16_t addr;
      if (sscanf(comma + 1, "%hu", &addr) == 1) {
        if (addr >= 1 && addr <= 247) {
          modbus_slave_addr = (uint8_t)addr;
          modbus.begin(modbus_slave_addr, Serial2);
          send_response("OK\n");
        } else {
          send_response("ERROR: Address out of range (1-247)\n");
        }
      } else {
        send_response("ERROR: Invalid address\n");
      }
    } else {
      send_response("ERROR: Missing address parameter\n");
    }
  }

  // MODB:ADDR? - Query target slave address
  else if (strcmp(cmd, "MODB:ADDR?") == 0 || strcmp(cmd, "MODB:ADDRESS?") == 0) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%u\n", modbus_slave_addr);
    send_response(buf);
  }

  // MODB:READ:HOLD,<reg>,<count> - Read holding registers (function code 0x03)
  else if (strncmp(cmd, "MODB:READ:HOLD", 14) == 0) {
    const char* comma1 = strchr(cmd, ',');
    if (!comma1) {
      send_response("ERROR: Missing parameters (reg,count)\n");
      return;
    }

    const char* comma2 = strchr(comma1 + 1, ',');
    if (!comma2) {
      send_response("ERROR: Missing count parameter\n");
      return;
    }

    uint16_t reg, count;
    if (sscanf(comma1 + 1, "%hu,%hu", &reg, &count) == 2) {
      if (count == 0 || count > 125) {
        send_response("ERROR: Count out of range (1-125)\n");
        return;
      }
      read_holding_registers(reg, count);
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // MODB:READ:INPU,<reg>,<count> - Read input registers (function code 0x04)
  else if (strncmp(cmd, "MODB:READ:INPU", 14) == 0) {
    const char* comma1 = strchr(cmd, ',');
    if (!comma1) {
      send_response("ERROR: Missing parameters (reg,count)\n");
      return;
    }

    const char* comma2 = strchr(comma1 + 1, ',');
    if (!comma2) {
      send_response("ERROR: Missing count parameter\n");
      return;
    }

    uint16_t reg, count;
    if (sscanf(comma1 + 1, "%hu,%hu", &reg, &count) == 2) {
      if (count == 0 || count > 125) {
        send_response("ERROR: Count out of range (1-125)\n");
        return;
      }
      read_input_registers(reg, count);
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // MODB:WRIT:HOLD,<reg>,<value> - Write single holding register (function code 0x06)
  else if (strncmp(cmd, "MODB:WRIT:HOLD", 14) == 0 || strncmp(cmd, "MODB:WRITE:HOLD", 15) == 0) {
    const char* comma1 = strchr(cmd, ',');
    if (!comma1) {
      send_response("ERROR: Missing parameters (reg,value)\n");
      return;
    }

    const char* comma2 = strchr(comma1 + 1, ',');
    if (!comma2) {
      send_response("ERROR: Missing value parameter\n");
      return;
    }

    uint16_t reg, value;
    if (sscanf(comma1 + 1, "%hu,%hu", &reg, &value) == 2) {
      write_holding_register(reg, value);
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // MODB:WRIT:COIL,<addr>,<0|1> - Write single coil (function code 0x05)
  else if (strncmp(cmd, "MODB:WRIT:COIL", 14) == 0 || strncmp(cmd, "MODB:WRITE:COIL", 15) == 0) {
    const char* comma1 = strchr(cmd, ',');
    if (!comma1) {
      send_response("ERROR: Missing parameters (addr,value)\n");
      return;
    }

    const char* comma2 = strchr(comma1 + 1, ',');
    if (!comma2) {
      send_response("ERROR: Missing value parameter\n");
      return;
    }

    uint16_t addr, value;
    if (sscanf(comma1 + 1, "%hu,%hu", &addr, &value) == 2) {
      if (value > 1) {
        send_response("ERROR: Value must be 0 or 1\n");
        return;
      }
      write_coil(addr, value == 1);
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
