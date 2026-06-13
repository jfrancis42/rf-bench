/*
 * SCPI CAN Bus Controller for ESP32
 *
 * Network-accessible CAN bus master bridge — send/receive CAN frames via SCPI
 * commands over TCP/IP. Supports standard (11-bit) and extended (29-bit) CAN IDs.
 *
 * Hardware:
 *   MCP2515 CAN controller + MCP2551 CAN transceiver
 *   SPI on VSPI: MOSI=23, MISO=19, SCK=18, CS=5
 *   INT=GPIO 4 (optional interrupt for RX — not used in polling mode)
 *   CAN_H/CAN_L to physical CAN bus
 *
 * Requires:
 *   MCP_CAN library (Seeed Studio fork or compatible)
 *   Install: Arduino Library Manager → "MCP_CAN" by coryjfowler
 *   Or: https://github.com/coryjfowler/MCP_CAN_lib
 *
 * CAN bus termination:
 *   120Ω resistor required at each end of the CAN bus (between CAN_H and CAN_L).
 *   Most development boards don't have on-board termination — add external 120Ω.
 *
 * Typical CAN baud rates:
 *   10 kbps, 20 kbps, 50 kbps, 100 kbps, 125 kbps, 250 kbps, 500 kbps, 1000 kbps
 *
 * SCPI port: 5025 (standard instrument port)
 */

#include <WiFi.h>
#include <SPI.h>
#include <mcp_can.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// MCP2515 SPI pins (ESP32 VSPI)
const int spi_cs_pin = 5;
const int spi_mosi_pin = 23;
const int spi_miso_pin = 19;
const int spi_sck_pin = 18;
const int can_int_pin = 4;  // Optional interrupt pin (not used in polling mode)

// MCP2515 CAN controller
MCP_CAN CAN(spi_cs_pin);

// CAN baud rate (default 500 kbps)
uint16_t can_baud = CAN_500KBPS;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// CAN receive buffer
struct CANFrame {
  uint32_t id;
  uint8_t ext;  // 0 = standard, 1 = extended
  uint8_t len;
  uint8_t data[8];
};

#define RX_BUFFER_SIZE 32
CANFrame rx_buffer[RX_BUFFER_SIZE];
int rx_head = 0;
int rx_tail = 0;

// CAN filter (default: accept all)
uint32_t filter_id = 0x000;
uint32_t filter_mask = 0x000;  // 0 = accept all

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI CAN Bus Controller");
  Serial.println("=======================");

  // Initialize SPI
  SPI.begin(spi_sck_pin, spi_miso_pin, spi_mosi_pin, spi_cs_pin);
  Serial.printf("SPI initialized: SCK=%d, MISO=%d, MOSI=%d, CS=%d\n",
                spi_sck_pin, spi_miso_pin, spi_mosi_pin, spi_cs_pin);

  // Initialize CAN controller
  Serial.print("Initializing MCP2515 CAN controller... ");
  if (CAN.begin(MCP_ANY, can_baud, MCP_8MHZ) == CAN_OK) {
    Serial.println("OK");
    CAN.setMode(MCP_NORMAL);
    Serial.println("MCP2515 set to normal mode");
  } else {
    Serial.println("FAILED");
    Serial.println("Check SPI wiring and MCP2515 power");
  }

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
  Serial.printf("CAN baud: %d kbps\n", baud_to_kbps(can_baud));
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

  // Poll CAN bus for incoming frames
  poll_can_rx();

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

// Poll CAN bus for incoming frames and store in circular buffer
void poll_can_rx() {
  if (CAN.checkReceive() != CAN_MSGAVAIL) {
    return;
  }

  // Check if buffer is full
  int next_head = (rx_head + 1) % RX_BUFFER_SIZE;
  if (next_head == rx_tail) {
    // Buffer full — drop oldest frame
    rx_tail = (rx_tail + 1) % RX_BUFFER_SIZE;
  }

  CANFrame* frame = &rx_buffer[rx_head];
  CAN.readMsgBuf(&frame->id, &frame->ext, &frame->len, frame->data);

  rx_head = next_head;
}

// Check if RX buffer has available frames
int rx_available() {
  return (rx_head - rx_tail + RX_BUFFER_SIZE) % RX_BUFFER_SIZE;
}

// Read next frame from RX buffer
bool read_rx_frame(CANFrame* frame) {
  if (rx_head == rx_tail) {
    return false;  // Buffer empty
  }

  *frame = rx_buffer[rx_tail];
  rx_tail = (rx_tail + 1) % RX_BUFFER_SIZE;
  return true;
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Convert baud constant to kbps
int baud_to_kbps(uint16_t baud_const) {
  switch (baud_const) {
    case CAN_5KBPS: return 5;
    case CAN_10KBPS: return 10;
    case CAN_20KBPS: return 20;
    case CAN_50KBPS: return 50;
    case CAN_100KBPS: return 100;
    case CAN_125KBPS: return 125;
    case CAN_250KBPS: return 250;
    case CAN_500KBPS: return 500;
    case CAN_1000KBPS: return 1000;
    default: return -1;
  }
}

// Convert kbps to baud constant
uint16_t kbps_to_baud(int kbps) {
  switch (kbps) {
    case 5: return CAN_5KBPS;
    case 10: return CAN_10KBPS;
    case 20: return CAN_20KBPS;
    case 50: return CAN_50KBPS;
    case 100: return CAN_100KBPS;
    case 125: return CAN_125KBPS;
    case 250: return CAN_250KBPS;
    case 500: return CAN_500KBPS;
    case 1000: return CAN_1000KBPS;
    default: return 0;
  }
}

// Parse hex bytes from comma-separated string
int parse_hex_bytes(const char* str, uint8_t* data, int max_len) {
  int count = 0;
  const char* p = str;

  while (*p && count < max_len) {
    // Skip whitespace and commas
    while (*p == ' ' || *p == '\t' || *p == ',') p++;
    if (!*p) break;

    // Parse hex byte
    uint32_t byte_val;
    if (sscanf(p, "%i", &byte_val) == 1) {
      if (byte_val > 0xFF) {
        return -1;  // Byte out of range
      }
      data[count++] = (uint8_t)byte_val;

      // Skip to next comma or end
      while (*p && *p != ',') p++;
      if (*p == ',') p++;
    } else {
      break;
    }
  }

  return count;
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
    send_response("N0GQ,ESP32-SCPI-CAN,1.0,2026\n");
  }

  // *RST - Reset (reinitialize CAN controller)
  else if (strcmp(cmd, "*RST") == 0) {
    CAN.reset();
    CAN.begin(MCP_ANY, can_baud, MCP_8MHZ);
    CAN.setMode(MCP_NORMAL);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // CAN:RATE,<kbps> - Set CAN baud rate
  else if (strncmp(cmd, "CAN:RATE", 8) == 0 && strchr(cmd, ',')) {
    const char* comma = strchr(cmd, ',');
    int kbps;
    if (sscanf(comma + 1, "%d", &kbps) == 1) {
      uint16_t baud_const = kbps_to_baud(kbps);
      if (baud_const == 0) {
        send_response("ERROR: Invalid rate (must be 5,10,20,50,100,125,250,500,1000 kbps)\n");
      } else {
        can_baud = baud_const;
        CAN.reset();
        if (CAN.begin(MCP_ANY, can_baud, MCP_8MHZ) == CAN_OK) {
          CAN.setMode(MCP_NORMAL);
          send_response("OK\n");
        } else {
          send_response("ERROR: Failed to set baud rate\n");
        }
      }
    } else {
      send_response("ERROR: Invalid rate parameter\n");
    }
  }

  // CAN:RATE? - Query CAN baud rate
  else if (strcmp(cmd, "CAN:RATE?") == 0) {
    int kbps = baud_to_kbps(can_baud);
    char buf[32];
    snprintf(buf, sizeof(buf), "%d\n", kbps);
    send_response(buf);
  }

  // CAN:SEND,<id>,<hex bytes> - Send standard CAN frame
  else if (strncmp(cmd, "CAN:SEND", 8) == 0 && strchr(cmd, ',')) {
    const char* params = strchr(cmd, ',');
    if (!params) {
      send_response("ERROR: Missing parameters\n");
      return;
    }

    // Parse ID
    uint32_t id;
    if (sscanf(params + 1, "%i", &id) != 1) {
      send_response("ERROR: Invalid ID\n");
      return;
    }

    if (id > 0x7FF) {
      send_response("ERROR: Standard ID out of range (0x000-0x7FF)\n");
      return;
    }

    // Parse data bytes
    const char* data_start = strchr(params + 1, ',');
    if (!data_start) {
      // No data bytes — send zero-length frame
      if (CAN.sendMsgBuf((unsigned long)id, 0, 0, NULL) == CAN_OK) {
        send_response("OK\n");
      } else {
        send_response("ERROR: CAN send failed\n");
      }
      return;
    }

    uint8_t data[8];
    int len = parse_hex_bytes(data_start + 1, data, 8);
    if (len < 0) {
      send_response("ERROR: Invalid data bytes (must be 0x00-0xFF)\n");
      return;
    }
    if (len > 8) {
      send_response("ERROR: Too many data bytes (max 8)\n");
      return;
    }

    if (CAN.sendMsgBuf((unsigned long)id, 0, len, data) == CAN_OK) {
      send_response("OK\n");
    } else {
      send_response("ERROR: CAN send failed\n");
    }
  }

  // CAN:SEND:EXT,<id>,<hex bytes> - Send extended CAN frame
  else if (strncmp(cmd, "CAN:SEND:EXT", 12) == 0 && strchr(cmd, ',')) {
    const char* params = strchr(cmd, ',');
    if (!params) {
      send_response("ERROR: Missing parameters\n");
      return;
    }

    // Parse ID
    uint32_t id;
    if (sscanf(params + 1, "%i", &id) != 1) {
      send_response("ERROR: Invalid ID\n");
      return;
    }

    if (id > 0x1FFFFFFF) {
      send_response("ERROR: Extended ID out of range (0x00000000-0x1FFFFFFF)\n");
      return;
    }

    // Parse data bytes
    const char* data_start = strchr(params + 1, ',');
    if (!data_start) {
      // No data bytes — send zero-length frame
      if (CAN.sendMsgBuf((unsigned long)id, 1, 0, NULL) == CAN_OK) {
        send_response("OK\n");
      } else {
        send_response("ERROR: CAN send failed\n");
      }
      return;
    }

    uint8_t data[8];
    int len = parse_hex_bytes(data_start + 1, data, 8);
    if (len < 0) {
      send_response("ERROR: Invalid data bytes (must be 0x00-0xFF)\n");
      return;
    }
    if (len > 8) {
      send_response("ERROR: Too many data bytes (max 8)\n");
      return;
    }

    if (CAN.sendMsgBuf((unsigned long)id, 1, len, data) == CAN_OK) {
      send_response("OK\n");
    } else {
      send_response("ERROR: CAN send failed\n");
    }
  }

  // CAN:READ? - Read next CAN frame from RX buffer
  else if (strcmp(cmd, "CAN:READ?") == 0) {
    CANFrame frame;
    if (!read_rx_frame(&frame)) {
      send_response("NONE\n");
      return;
    }

    // Build response: id,ext,len,data_hex_csv
    char buf[128];
    int offset = 0;

    if (frame.ext) {
      offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%08X,1,%d", frame.id, frame.len);
    } else {
      offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%03X,0,%d", frame.id, frame.len);
    }

    if (frame.len > 0) {
      buf[offset++] = ',';
      for (int i = 0; i < frame.len; i++) {
        offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", frame.data[i]);
        if (i < frame.len - 1) {
          buf[offset++] = ',';
        }
      }
    }

    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  }

  // CAN:AVAI? - Query number of frames available in RX buffer
  else if (strcmp(cmd, "CAN:AVAI?") == 0) {
    int count = rx_available();
    char buf[16];
    snprintf(buf, sizeof(buf), "%d\n", count);
    send_response(buf);
  }

  // CAN:FILT,<id>,<mask> - Set CAN filter and mask
  else if (strncmp(cmd, "CAN:FILT", 8) == 0 && strchr(cmd, ',')) {
    const char* params = strchr(cmd, ',');
    if (!params) {
      send_response("ERROR: Missing parameters\n");
      return;
    }

    uint32_t id, mask;
    if (sscanf(params + 1, "%i,%i", &id, &mask) != 2) {
      send_response("ERROR: Invalid parameters (need id,mask)\n");
      return;
    }

    filter_id = id;
    filter_mask = mask;

    // Apply filter (mask 0 = accept all)
    CAN.init_Mask(0, 0, mask);
    CAN.init_Mask(1, 0, mask);
    CAN.init_Filt(0, 0, id);
    CAN.init_Filt(1, 0, id);

    send_response("OK\n");
  }

  // CAN:FILT? - Query current filter and mask
  else if (strcmp(cmd, "CAN:FILT?") == 0) {
    char buf[64];
    snprintf(buf, sizeof(buf), "0x%08X,0x%08X\n", filter_id, filter_mask);
    send_response(buf);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
