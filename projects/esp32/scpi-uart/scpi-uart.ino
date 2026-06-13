/*
 * SCPI UART Controller for ESP32
 *
 * UART bridge — configure baud rate, data bits, parity, stop bits, read/write via SCPI over TCP/IP
 * Compatible with any UART device (GPS modules, sensors, radios, displays, modems, etc.)
 *
 * Hardware connections:
 *   UART2 (hardware serial):
 *     RX -> GPIO 16 (connects to TX of external device)
 *     TX -> GPIO 17 (connects to RX of external device)
 *     GND -> common ground with external device
 *
 * Supported configurations:
 *   Baud: 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400,
 *         57600, 115200, 230400, 460800, 921600
 *   Data bits: 5, 6, 7, 8
 *   Parity: None, Even, Odd
 *   Stop bits: 1, 2
 *
 * SCPI commands:
 *   UART:BAUD,<rate> — set baud rate
 *   UART:BAUD? — query baud rate
 *   UART:CONF,<config> — set data/parity/stop (e.g., 8N1, 7E1, 8O1)
 *   UART:CONF? — query config
 *   UART:WRIT,<hex bytes> — write hex bytes (e.g., UART:WRIT,0x41,0x42,0x43)
 *   UART:READ? — read all available bytes as hex CSV
 *   UART:READ? <timeout_ms> — read with timeout, return all received bytes as hex CSV
 *   UART:AVAI? — query bytes available in RX buffer
 *   UART:FLUS — flush RX buffer
 */

#include <WiFi.h>
#include <HardwareSerial.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// UART2 pins
const int uart_rx_pin = 16;
const int uart_tx_pin = 17;

// UART2 configuration
uint32_t uart_baud = 9600;
uint32_t uart_config = SERIAL_8N1;  // 8 data bits, no parity, 1 stop bit

// UART2 object
HardwareSerial uart2(2);  // UART2

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// Response buffer (for large reads)
char response_buffer[1024];

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI UART Controller");
  Serial.println("====================");

  // Initialize UART2
  uart2.begin(uart_baud, uart_config, uart_rx_pin, uart_tx_pin);
  Serial.printf("UART2 initialized: RX=%d, TX=%d, baud=%u, config=8N1\n",
                uart_rx_pin, uart_tx_pin, uart_baud);

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

// Parse UART config string (8N1, 7E1, 8O1, etc.)
bool parse_uart_config(const char* config_str, uint32_t* config_out) {
  if (strlen(config_str) != 3) return false;

  uint8_t data_bits = config_str[0] - '0';
  char parity = toupper(config_str[1]);
  uint8_t stop_bits = config_str[2] - '0';

  // Validate data bits (5-8)
  if (data_bits < 5 || data_bits > 8) return false;

  // Validate parity (N, E, O)
  if (parity != 'N' && parity != 'E' && parity != 'O') return false;

  // Validate stop bits (1-2)
  if (stop_bits < 1 || stop_bits > 2) return false;

  // Build config value
  uint32_t config = 0;

  // Data bits
  switch (data_bits) {
    case 5: config |= SERIAL_5N1 & 0x0F; break;
    case 6: config |= SERIAL_6N1 & 0x0F; break;
    case 7: config |= SERIAL_7N1 & 0x0F; break;
    case 8: config |= SERIAL_8N1 & 0x0F; break;
  }

  // Parity
  if (parity == 'N') {
    // No parity (already set above)
  } else if (parity == 'E') {
    config |= 0x02 << 4;  // Even parity
  } else if (parity == 'O') {
    config |= 0x03 << 4;  // Odd parity
  }

  // Stop bits
  if (stop_bits == 2) {
    config |= 0x01 << 2;  // 2 stop bits
  }

  // Reconstruct proper constant
  // ESP32 UART config format: 0x800001c (example)
  // We need to build SERIAL_xXy format
  if (data_bits == 8 && parity == 'N' && stop_bits == 1) {
    config = SERIAL_8N1;
  } else if (data_bits == 7 && parity == 'E' && stop_bits == 1) {
    config = SERIAL_7E1;
  } else if (data_bits == 8 && parity == 'E' && stop_bits == 1) {
    config = SERIAL_8E1;
  } else if (data_bits == 8 && parity == 'O' && stop_bits == 1) {
    config = SERIAL_8O1;
  } else if (data_bits == 7 && parity == 'N' && stop_bits == 1) {
    config = SERIAL_7N1;
  } else if (data_bits == 7 && parity == 'O' && stop_bits == 1) {
    config = SERIAL_7O1;
  } else if (data_bits == 6 && parity == 'N' && stop_bits == 1) {
    config = SERIAL_6N1;
  } else if (data_bits == 6 && parity == 'E' && stop_bits == 1) {
    config = SERIAL_6E1;
  } else if (data_bits == 6 && parity == 'O' && stop_bits == 1) {
    config = SERIAL_6O1;
  } else if (data_bits == 5 && parity == 'N' && stop_bits == 1) {
    config = SERIAL_5N1;
  } else if (data_bits == 5 && parity == 'E' && stop_bits == 1) {
    config = SERIAL_5E1;
  } else if (data_bits == 5 && parity == 'O' && stop_bits == 1) {
    config = SERIAL_5O1;
  } else if (data_bits == 8 && parity == 'N' && stop_bits == 2) {
    config = SERIAL_8N2;
  } else if (data_bits == 8 && parity == 'E' && stop_bits == 2) {
    config = SERIAL_8E2;
  } else if (data_bits == 8 && parity == 'O' && stop_bits == 2) {
    config = SERIAL_8O2;
  } else if (data_bits == 7 && parity == 'N' && stop_bits == 2) {
    config = SERIAL_7N2;
  } else if (data_bits == 7 && parity == 'E' && stop_bits == 2) {
    config = SERIAL_7E2;
  } else if (data_bits == 7 && parity == 'O' && stop_bits == 2) {
    config = SERIAL_7O2;
  } else if (data_bits == 6 && parity == 'N' && stop_bits == 2) {
    config = SERIAL_6N2;
  } else if (data_bits == 6 && parity == 'E' && stop_bits == 2) {
    config = SERIAL_6E2;
  } else if (data_bits == 6 && parity == 'O' && stop_bits == 2) {
    config = SERIAL_6O2;
  } else if (data_bits == 5 && parity == 'N' && stop_bits == 2) {
    config = SERIAL_5N2;
  } else if (data_bits == 5 && parity == 'E' && stop_bits == 2) {
    config = SERIAL_5E2;
  } else if (data_bits == 5 && parity == 'O' && stop_bits == 2) {
    config = SERIAL_5O2;
  } else {
    return false;  // Unsupported combination
  }

  *config_out = config;
  return true;
}

// Format UART config as string (8N1, 7E1, etc.)
void format_uart_config(uint32_t config, char* buf, size_t buf_size) {
  // ESP32 UART config constants
  uint8_t data_bits = 8;
  char parity = 'N';
  uint8_t stop_bits = 1;

  // Decode config (this is a simplified approach - match against known constants)
  if (config == SERIAL_5N1) { data_bits = 5; parity = 'N'; stop_bits = 1; }
  else if (config == SERIAL_6N1) { data_bits = 6; parity = 'N'; stop_bits = 1; }
  else if (config == SERIAL_7N1) { data_bits = 7; parity = 'N'; stop_bits = 1; }
  else if (config == SERIAL_8N1) { data_bits = 8; parity = 'N'; stop_bits = 1; }
  else if (config == SERIAL_5E1) { data_bits = 5; parity = 'E'; stop_bits = 1; }
  else if (config == SERIAL_6E1) { data_bits = 6; parity = 'E'; stop_bits = 1; }
  else if (config == SERIAL_7E1) { data_bits = 7; parity = 'E'; stop_bits = 1; }
  else if (config == SERIAL_8E1) { data_bits = 8; parity = 'E'; stop_bits = 1; }
  else if (config == SERIAL_5O1) { data_bits = 5; parity = 'O'; stop_bits = 1; }
  else if (config == SERIAL_6O1) { data_bits = 6; parity = 'O'; stop_bits = 1; }
  else if (config == SERIAL_7O1) { data_bits = 7; parity = 'O'; stop_bits = 1; }
  else if (config == SERIAL_8O1) { data_bits = 8; parity = 'O'; stop_bits = 1; }
  else if (config == SERIAL_5N2) { data_bits = 5; parity = 'N'; stop_bits = 2; }
  else if (config == SERIAL_6N2) { data_bits = 6; parity = 'N'; stop_bits = 2; }
  else if (config == SERIAL_7N2) { data_bits = 7; parity = 'N'; stop_bits = 2; }
  else if (config == SERIAL_8N2) { data_bits = 8; parity = 'N'; stop_bits = 2; }
  else if (config == SERIAL_5E2) { data_bits = 5; parity = 'E'; stop_bits = 2; }
  else if (config == SERIAL_6E2) { data_bits = 6; parity = 'E'; stop_bits = 2; }
  else if (config == SERIAL_7E2) { data_bits = 7; parity = 'E'; stop_bits = 2; }
  else if (config == SERIAL_8E2) { data_bits = 8; parity = 'E'; stop_bits = 2; }
  else if (config == SERIAL_5O2) { data_bits = 5; parity = 'O'; stop_bits = 2; }
  else if (config == SERIAL_6O2) { data_bits = 6; parity = 'O'; stop_bits = 2; }
  else if (config == SERIAL_7O2) { data_bits = 7; parity = 'O'; stop_bits = 2; }
  else if (config == SERIAL_8O2) { data_bits = 8; parity = 'O'; stop_bits = 2; }

  snprintf(buf, buf_size, "%d%c%d", data_bits, parity, stop_bits);
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
    send_response("N0GQ,ESP32-SCPI-UART,1.0,2026\n");
  }

  // *RST - Reset (back to 9600 8N1)
  else if (strcmp(cmd, "*RST") == 0) {
    uart_baud = 9600;
    uart_config = SERIAL_8N1;
    uart2.begin(uart_baud, uart_config, uart_rx_pin, uart_tx_pin);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // UART:BAUD,<rate> - Set baud rate
  else if (strncmp(cmd, "UART:BAUD", 9) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      uint32_t new_baud;
      if (sscanf(comma + 1, "%u", &new_baud) == 1) {
        // Validate baud rate (common rates only)
        if (new_baud == 300 || new_baud == 600 || new_baud == 1200 || new_baud == 2400 ||
            new_baud == 4800 || new_baud == 9600 || new_baud == 14400 || new_baud == 19200 ||
            new_baud == 28800 || new_baud == 38400 || new_baud == 57600 || new_baud == 115200 ||
            new_baud == 230400 || new_baud == 460800 || new_baud == 921600) {
          uart_baud = new_baud;
          uart2.begin(uart_baud, uart_config, uart_rx_pin, uart_tx_pin);
          send_response("OK\n");
        } else {
          send_response("ERROR: Invalid baud rate (300-921600)\n");
        }
      } else {
        send_response("ERROR: Invalid baud rate\n");
      }
    } else {
      send_response("ERROR: Missing baud rate parameter\n");
    }
  }

  // UART:BAUD? - Query baud rate
  else if (strcmp(cmd, "UART:BAUD?") == 0) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%u\n", uart_baud);
    send_response(buf);
  }

  // UART:CONF,<8N1|7E1|etc> - Set UART config
  else if (strncmp(cmd, "UART:CONF", 9) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      // Skip leading whitespace after comma
      const char* config_str = comma + 1;
      while (*config_str == ' ' || *config_str == '\t') config_str++;

      uint32_t new_config;
      if (parse_uart_config(config_str, &new_config)) {
        uart_config = new_config;
        uart2.begin(uart_baud, uart_config, uart_rx_pin, uart_tx_pin);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid config (use 8N1, 7E1, 8O1, etc.)\n");
      }
    } else {
      send_response("ERROR: Missing config parameter\n");
    }
  }

  // UART:CONF? - Query UART config
  else if (strcmp(cmd, "UART:CONF?") == 0) {
    char buf[16];
    format_uart_config(uart_config, buf, sizeof(buf));
    strncat(buf, "\n", sizeof(buf) - strlen(buf) - 1);
    send_response(buf);
  }

  // UART:WRIT,<hex bytes> - Write bytes
  else if (strncmp(cmd, "UART:WRIT", 9) == 0 || strncmp(cmd, "UART:WRITE", 10) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (!comma) {
      send_response("ERROR: Missing data bytes\n");
      return;
    }

    // Parse hex bytes
    uint8_t data[256];
    int count = 0;
    const char* p = comma;

    while (p && count < 256) {
      p++; // Skip comma or space
      while (*p == ' ' || *p == '\t') p++; // Skip whitespace

      if (*p == '\0') break;

      uint32_t byte_val;
      if (sscanf(p, "%i", &byte_val) == 1) {
        if (byte_val > 0xFF) {
          send_response("ERROR: Byte value out of range (0x00-0xFF)\n");
          return;
        }
        data[count++] = (uint8_t)byte_val;
        p = strchr(p, ',');
        if (!p) break;
      } else {
        break;
      }
    }

    if (count == 0) {
      send_response("ERROR: No data to write\n");
      return;
    }

    // Write to UART2
    uart2.write(data, count);
    send_response("OK\n");
  }

  // UART:READ? [timeout_ms] - Read bytes (with optional timeout)
  else if (strncmp(cmd, "UART:READ?", 10) == 0) {
    // Check for timeout parameter
    uint32_t timeout_ms = 0;
    const char* space = strchr(cmd, ' ');
    if (space) {
      sscanf(space + 1, "%u", &timeout_ms);
    }

    // Wait for data if timeout specified
    if (timeout_ms > 0) {
      uint32_t start = millis();
      while (uart2.available() == 0 && (millis() - start) < timeout_ms) {
        delay(1);
      }
    }

    // Read available bytes
    int available = uart2.available();
    if (available == 0) {
      send_response("NONE\n");
      return;
    }

    // Build hex CSV response
    char buf[1024];
    int offset = 0;
    bool first = true;

    while (uart2.available() && offset < sizeof(buf) - 10) {
      uint8_t byte = uart2.read();
      if (!first) {
        buf[offset++] = ',';
      }
      offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", byte);
      first = false;
    }

    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  }

  // UART:AVAI? - Query bytes available
  else if (strcmp(cmd, "UART:AVAI?") == 0 || strcmp(cmd, "UART:AVAILABLE?") == 0) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%d\n", uart2.available());
    send_response(buf);
  }

  // UART:FLUS - Flush RX buffer
  else if (strcmp(cmd, "UART:FLUS") == 0 || strcmp(cmd, "UART:FLUSH") == 0) {
    while (uart2.available()) {
      uart2.read();
    }
    send_response("OK\n");
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
