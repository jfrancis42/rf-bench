/*
 * SCPI SPI Controller for ESP32
 *
 * SPI master bridge — control SPI devices via SCPI commands over TCP/IP
 * Compatible with any SPI slave device (ADCs, DACs, displays, memory, sensors, etc.)
 *
 * Hardware connections:
 *   SPI Master (ESP32 VSPI):
 *     MOSI -> GPIO 23 (Master Out, Slave In)
 *     MISO -> GPIO 19 (Master In, Slave Out)
 *     SCK  -> GPIO 18 (Clock)
 *     CS0  -> GPIO 5  (Chip Select 0)
 *     CS1  -> GPIO 15 (Chip Select 1)
 *     CS2  -> GPIO 4  (Chip Select 2)
 *     CS3  -> GPIO 16 (Chip Select 3)
 *
 * Common SPI devices:
 *   MCP3008   8-channel 10-bit ADC
 *   MCP4921   12-bit DAC
 *   MAX7219   LED display driver
 *   NRF24L01  2.4 GHz wireless transceiver
 *   W25Q32    32 Mbit SPI flash
 *   BME280    Temp/pressure/humidity sensor (SPI or I2C)
 *   MCP23S17  16-bit I/O expander
 *   AD9833    Function generator IC
 *
 * Note: SPI is full-duplex — every write also receives data. The controller
 * returns MISO data for all transfer commands.
 */

#include <WiFi.h>
#include <SPI.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// SPI pins (ESP32 VSPI)
const int spi_mosi_pin = 23;
const int spi_miso_pin = 19;
const int spi_sck_pin  = 18;
const int spi_cs_pins[4] = {5, 15, 4, 16}; // CS0, CS1, CS2, CS3

// SPI settings (defaults)
uint32_t spi_frequency = 1000000; // 1 MHz default
uint8_t spi_mode = SPI_MODE0;     // CPOL=0, CPHA=0
uint8_t spi_bit_order = MSBFIRST;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// Response buffer (for large transfers)
char response_buffer[512];

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI SPI Controller");
  Serial.println("===================");

  // Initialize CS pins (all HIGH = deselected)
  for (int i = 0; i < 4; i++) {
    pinMode(spi_cs_pins[i], OUTPUT);
    digitalWrite(spi_cs_pins[i], HIGH);
  }

  // Initialize SPI
  SPI.begin(spi_sck_pin, spi_miso_pin, spi_mosi_pin, -1); // CS handled manually
  SPI.setFrequency(spi_frequency);
  SPI.setDataMode(spi_mode);
  SPI.setBitOrder(spi_bit_order);

  Serial.printf("SPI initialized: MOSI=%d, MISO=%d, SCK=%d\n",
                spi_mosi_pin, spi_miso_pin, spi_sck_pin);
  Serial.printf("CS pins: CS0=%d, CS1=%d, CS2=%d, CS3=%d\n",
                spi_cs_pins[0], spi_cs_pins[1], spi_cs_pins[2], spi_cs_pins[3]);
  Serial.printf("Frequency: %u Hz, Mode: %d, Bit order: %s\n",
                spi_frequency, spi_mode, spi_bit_order == MSBFIRST ? "MSB" : "LSB");

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

// Parse CS channel from (@n) notation
int parse_cs_channel(const char* str) {
  const char* at = strchr(str, '@');
  if (!at) return -1;

  int cs;
  if (sscanf(at, "@%d)", &cs) == 1) {
    if (cs >= 0 && cs <= 3) {
      return cs;
    }
  }
  return -1;
}

// Parse hex bytes from comma-separated string
// Format: 0x12,0x34,0xAB or 12,34,AB (hex allowed without 0x prefix)
int parse_hex_bytes(const char* str, uint8_t* buf, int max_len) {
  int count = 0;
  const char* p = str;

  while (*p && count < max_len) {
    // Skip whitespace and commas
    while (*p == ' ' || *p == '\t' || *p == ',') p++;
    if (!*p) break;

    // Parse hex value
    uint32_t val;
    if (sscanf(p, "%i", &val) == 1) {
      if (val > 0xFF) {
        return -1; // Byte value out of range
      }
      buf[count++] = (uint8_t)val;

      // Skip to next comma or end
      while (*p && *p != ',') p++;
      if (*p == ',') p++;
    } else {
      return -1; // Parse error
    }
  }

  return count;
}

// SPI transfer (full-duplex: write and read simultaneously)
void spi_transfer(int cs, uint8_t* tx_data, uint8_t* rx_data, int len) {
  digitalWrite(spi_cs_pins[cs], LOW);
  delayMicroseconds(1); // CS setup time

  for (int i = 0; i < len; i++) {
    rx_data[i] = SPI.transfer(tx_data[i]);
  }

  delayMicroseconds(1); // CS hold time
  digitalWrite(spi_cs_pins[cs], HIGH);
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
    send_response("N0GQ,ESP32-SCPI-SPI,1.0,2026\n");
  }

  // *RST - Reset (return to default settings)
  else if (strcmp(cmd, "*RST") == 0) {
    spi_frequency = 1000000;
    spi_mode = SPI_MODE0;
    spi_bit_order = MSBFIRST;
    SPI.setFrequency(spi_frequency);
    SPI.setDataMode(spi_mode);
    SPI.setBitOrder(spi_bit_order);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // SPI:FREQ <hz> - Set SPI clock frequency
  else if (strncmp(cmd, "SPI:FREQ", 8) == 0 || strncmp(cmd, "SPI:FREQUENCY", 13) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      uint32_t freq;
      if (sscanf(comma + 1, "%u", &freq) == 1) {
        if (freq >= 100000 && freq <= 10000000) {
          spi_frequency = freq;
          SPI.setFrequency(spi_frequency);
          send_response("OK\n");
        } else {
          send_response("ERROR: Frequency out of range (100k-10M Hz)\n");
        }
      } else {
        send_response("ERROR: Invalid frequency\n");
      }
    } else {
      send_response("ERROR: Missing frequency parameter\n");
    }
  }

  // SPI:FREQ? - Query SPI clock frequency
  else if (strcmp(cmd, "SPI:FREQ?") == 0 || strcmp(cmd, "SPI:FREQUENCY?") == 0) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%u\n", spi_frequency);
    send_response(buf);
  }

  // SPI:MODE <0-3> - Set SPI mode (CPOL/CPHA)
  else if (strncmp(cmd, "SPI:MODE", 8) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      int mode;
      if (sscanf(comma + 1, "%d", &mode) == 1) {
        if (mode >= 0 && mode <= 3) {
          spi_mode = mode;
          SPI.setDataMode(spi_mode);
          send_response("OK\n");
        } else {
          send_response("ERROR: Mode must be 0-3\n");
        }
      } else {
        send_response("ERROR: Invalid mode\n");
      }
    } else {
      send_response("ERROR: Missing mode parameter\n");
    }
  }

  // SPI:MODE? - Query SPI mode
  else if (strcmp(cmd, "SPI:MODE?") == 0) {
    char buf[8];
    snprintf(buf, sizeof(buf), "%d\n", spi_mode);
    send_response(buf);
  }

  // SPI:ORD <MSB|LSB> - Set bit order
  else if (strncmp(cmd, "SPI:ORD", 7) == 0 || strncmp(cmd, "SPI:ORDER", 9) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      // Skip whitespace
      while (*comma == ',' || *comma == ' ' || *comma == '\t') comma++;

      if (strncmp(comma, "MSB", 3) == 0) {
        spi_bit_order = MSBFIRST;
        SPI.setBitOrder(spi_bit_order);
        send_response("OK\n");
      } else if (strncmp(comma, "LSB", 3) == 0) {
        spi_bit_order = LSBFIRST;
        SPI.setBitOrder(spi_bit_order);
        send_response("OK\n");
      } else {
        send_response("ERROR: Order must be MSB or LSB\n");
      }
    } else {
      send_response("ERROR: Missing order parameter\n");
    }
  }

  // SPI:ORD? - Query bit order
  else if (strcmp(cmd, "SPI:ORD?") == 0 || strcmp(cmd, "SPI:ORDER?") == 0) {
    send_response(spi_bit_order == MSBFIRST ? "MSB\n" : "LSB\n");
  }

  // SPI:TRAN (@cs),<hex bytes> - Transfer (write and read)
  else if (strncmp(cmd, "SPI:TRAN", 8) == 0 || strncmp(cmd, "SPI:TRANSFER", 12) == 0) {
    int cs = parse_cs_channel(cmd);
    if (cs < 0) {
      send_response("ERROR: Invalid CS channel (@0-@3)\n");
      return;
    }

    // Find comma after CS channel
    const char* close_paren = strchr(cmd, ')');
    if (!close_paren) {
      send_response("ERROR: Missing closing parenthesis\n");
      return;
    }

    const char* comma = strchr(close_paren, ',');
    if (!comma) {
      send_response("ERROR: Missing data bytes\n");
      return;
    }

    // Parse hex bytes
    uint8_t tx_buf[128];
    uint8_t rx_buf[128];
    int len = parse_hex_bytes(comma + 1, tx_buf, sizeof(tx_buf));

    if (len < 0) {
      send_response("ERROR: Invalid hex data\n");
      return;
    }
    if (len == 0) {
      send_response("ERROR: No data to transfer\n");
      return;
    }

    // Perform SPI transfer
    spi_transfer(cs, tx_buf, rx_buf, len);

    // Build response (hex CSV)
    char buf[512];
    int offset = 0;
    for (int i = 0; i < len && offset < sizeof(buf) - 10; i++) {
      if (i > 0) buf[offset++] = ',';
      offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", rx_buf[i]);
    }
    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  }

  // SPI:WRIT (@cs),<hex bytes> - Write only (ignore MISO)
  else if (strncmp(cmd, "SPI:WRIT", 8) == 0 || strncmp(cmd, "SPI:WRITE", 9) == 0) {
    int cs = parse_cs_channel(cmd);
    if (cs < 0) {
      send_response("ERROR: Invalid CS channel (@0-@3)\n");
      return;
    }

    // Find comma after CS channel
    const char* close_paren = strchr(cmd, ')');
    if (!close_paren) {
      send_response("ERROR: Missing closing parenthesis\n");
      return;
    }

    const char* comma = strchr(close_paren, ',');
    if (!comma) {
      send_response("ERROR: Missing data bytes\n");
      return;
    }

    // Parse hex bytes
    uint8_t tx_buf[128];
    uint8_t rx_buf[128];
    int len = parse_hex_bytes(comma + 1, tx_buf, sizeof(tx_buf));

    if (len < 0) {
      send_response("ERROR: Invalid hex data\n");
      return;
    }
    if (len == 0) {
      send_response("ERROR: No data to write\n");
      return;
    }

    // Perform SPI transfer (discard MISO)
    spi_transfer(cs, tx_buf, rx_buf, len);
    send_response("OK\n");
  }

  // SPI:READ (@cs),<count> - Read only (send 0x00 on MOSI)
  else if (strncmp(cmd, "SPI:READ", 8) == 0) {
    int cs = parse_cs_channel(cmd);
    if (cs < 0) {
      send_response("ERROR: Invalid CS channel (@0-@3)\n");
      return;
    }

    // Find comma after CS channel
    const char* close_paren = strchr(cmd, ')');
    if (!close_paren) {
      send_response("ERROR: Missing closing parenthesis\n");
      return;
    }

    const char* comma = strchr(close_paren, ',');
    if (!comma) {
      send_response("ERROR: Missing count parameter\n");
      return;
    }

    int count;
    if (sscanf(comma + 1, "%d", &count) != 1 || count <= 0 || count > 128) {
      send_response("ERROR: Invalid count (1-128)\n");
      return;
    }

    // Prepare TX buffer (all zeros)
    uint8_t tx_buf[128];
    uint8_t rx_buf[128];
    memset(tx_buf, 0, count);

    // Perform SPI transfer
    spi_transfer(cs, tx_buf, rx_buf, count);

    // Build response (hex CSV)
    char buf[512];
    int offset = 0;
    for (int i = 0; i < count && offset < sizeof(buf) - 10; i++) {
      if (i > 0) buf[offset++] = ',';
      offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", rx_buf[i]);
    }
    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
