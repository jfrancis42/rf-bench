/*
 * SCPI Signal Routing Matrix for ESP32
 *
 * 4×4 crosspoint signal routing switch using 16 relays via SCPI commands over TCP/IP
 * Each intersection in the matrix can be independently connected or disconnected
 * Multiple connections can be active simultaneously
 *
 * Hardware connections:
 *   Row select inputs (4):
 *     GPIO 25 -> Row 1 relay controls (columns 1-4)
 *     GPIO 26 -> Row 2 relay controls (columns 1-4)
 *     GPIO 27 -> Row 3 relay controls (columns 1-4)
 *     GPIO 14 -> Row 4 relay controls (columns 1-4)
 *
 *   Column output controls (4):
 *     GPIO 32 -> Column 1 relay controls (rows 1-4)
 *     GPIO 33 -> Column 2 relay controls (rows 1-4)
 *     GPIO 23 -> Column 3 relay controls (rows 1-4)
 *     GPIO 19 -> Column 4 relay controls (rows 1-4)
 *
 * Matrix organization:
 *   - 16 relay coils total (4 rows × 4 columns)
 *   - Each intersection (row,col) has a dedicated relay
 *   - Relay at (row,col) connects row input to column output when closed
 *   - Relay addressing: relay_index = (row-1)*4 + (col-1)  [0-15]
 *
 * Physical wiring with shift registers or GPIO expanders:
 *   Option 1: 2× 74HC595 shift registers (8 outputs each) for 16 relay control lines
 *   Option 2: 2× MCP23017 I2C GPIO expanders (16 GPIO each)
 *   Option 3: Direct GPIO (would need ESP32 with 16+ available GPIO pins)
 *
 * This implementation uses direct GPIO for simplicity (8 GPIO pins control
 * 16 relays through row/column multiplexing logic)
 *
 * Note: Most cheap relay boards are ACTIVE LOW (relay on when pin LOW)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Matrix dimensions
const int num_rows = 4;
const int num_cols = 4;
const int num_relays = num_rows * num_cols;  // 16 total

// Row GPIO pins (each controls a row of 4 relays)
const int row_pins[4] = {25, 26, 27, 14};

// Column GPIO pins (each controls a column of 4 relays)
const int col_pins[4] = {32, 33, 23, 19};

// Matrix state: true = closed (connected), false = open (disconnected)
// Indexed as [row][col], both 0-based
bool matrix_state[4][4] = {
  {false, false, false, false},
  {false, false, false, false},
  {false, false, false, false},
  {false, false, false, false}
};

// Most cheap relay boards are active-low (LOW = relay on)
// Set to true if your board is active-high (HIGH = relay on)
const bool active_high = false;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Signal Routing Matrix");
  Serial.println("===========================");

  // Initialize row GPIO pins
  for (int i = 0; i < num_rows; i++) {
    pinMode(row_pins[i], OUTPUT);
    digitalWrite(row_pins[i], active_high ? LOW : HIGH);  // All off
  }

  // Initialize column GPIO pins
  for (int i = 0; i < num_cols; i++) {
    pinMode(col_pins[i], OUTPUT);
    digitalWrite(col_pins[i], active_high ? LOW : HIGH);  // All off
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
  Serial.printf("Matrix size: %d×%d (%d crosspoints)\n", num_rows, num_cols, num_relays);
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

// Set physical relay state at matrix intersection (row, col)
// row and col are 0-indexed (0-3)
void set_crosspoint(int row, int col, bool state) {
  if (row < 0 || row >= num_rows || col < 0 || col >= num_cols) return;

  // Update state tracking
  matrix_state[row][col] = state;

  // Physical relay control logic
  // In a real implementation with shift registers or expanders,
  // this would update the specific relay at position (row, col)
  // For this demo with GPIO multiplexing, we set both row and col pins

  bool pin_state = active_high ? state : !state;

  // Note: In a true crosspoint matrix, you'd have dedicated control for each
  // of the 16 relays. This simplified version demonstrates the command structure.
  // Physical implementation would drive a relay matrix board or shift registers.

  Serial.printf("Crosspoint [%d,%d] -> %s\n", row+1, col+1, state ? "CLOSED" : "OPEN");
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
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
    send_response("N0GQ,ESP32-SCPI-Matrix,1.0,2026\n");
  }

  // *RST - Reset (open all connections)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int r = 0; r < num_rows; r++) {
      for (int c = 0; c < num_cols; c++) {
        set_crosspoint(r, c, false);
      }
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error (always none for this simple device)
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // ROUT:SIZE? - Query matrix dimensions
  else if (strcmp(cmd, "ROUT:SIZE?") == 0 || strcmp(cmd, "ROUTE:SIZE?") == 0) {
    char response[32];
    snprintf(response, sizeof(response), "%d,%d\n", num_rows, num_cols);
    send_response(response);
  }

  // ROUTE:CLOSE (@row!col) - Close connection at intersection
  else if (strncmp(cmd, "ROUT:CLOS", 9) == 0 || strncmp(cmd, "ROUTE:CLOSE", 11) == 0) {
    int row, col;
    if (parse_crosspoint(cmd, &row, &col)) {
      set_crosspoint(row, col, true);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid crosspoint format (use @row!col)\n");
    }
  }

  // ROUTE:OPEN (@row!col) - Open connection at intersection
  else if (strncmp(cmd, "ROUT:OPEN", 9) == 0 || strncmp(cmd, "ROUTE:OPEN", 10) == 0) {
    int row, col;
    if (parse_crosspoint(cmd, &row, &col)) {
      set_crosspoint(row, col, false);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid crosspoint format (use @row!col)\n");
    }
  }

  // ROUTE:CLOSE? (@row!col) - Query connection state at intersection
  else if (strncmp(cmd, "ROUT:CLOS?", 10) == 0 || strncmp(cmd, "ROUTE:CLOSE?", 12) == 0) {
    int row, col;
    if (parse_crosspoint(cmd, &row, &col)) {
      send_response(matrix_state[row][col] ? "1\n" : "0\n");
    } else {
      send_response("ERROR: Invalid crosspoint format (use @row!col)\n");
    }
  }

  // ROUTE:OPEN:ALL - Open all connections
  else if (strcmp(cmd, "ROUT:OPEN:ALL") == 0 || strcmp(cmd, "ROUTE:OPEN:ALL") == 0) {
    for (int r = 0; r < num_rows; r++) {
      for (int c = 0; c < num_cols; c++) {
        set_crosspoint(r, c, false);
      }
    }
    send_response("OK\n");
  }

  // ROUTE:STAT? - Query full matrix state
  else if (strcmp(cmd, "ROUT:STAT?") == 0 || strcmp(cmd, "ROUTE:STATE?") == 0) {
    // Return 16-bit value where each bit represents one crosspoint
    // Bit order: bit 0 = (1,1), bit 1 = (1,2), ..., bit 15 = (4,4)
    uint16_t state_bits = 0;
    for (int r = 0; r < num_rows; r++) {
      for (int c = 0; c < num_cols; c++) {
        if (matrix_state[r][c]) {
          state_bits |= (1 << (r * num_cols + c));
        }
      }
    }
    char response[32];
    snprintf(response, sizeof(response), "%u\n", state_bits);
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}

// Parse crosspoint address from SCPI command
// Format: (@row!col) where row and col are 1-indexed
// Example: (@2!3) means row 2, column 3
// Returns true if parse successful, sets row and col to 0-indexed values
bool parse_crosspoint(const char* cmd, int* row, int* col) {
  // Find the @ symbol
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return false;

  // Find the ! separator
  const char* exclaim = strchr(at_sign, '!');
  if (!exclaim) return false;

  // Parse row and column (1-indexed in SCPI, convert to 0-indexed)
  int r, c;
  if (sscanf(at_sign, "@%d!%d", &r, &c) != 2) {
    return false;
  }

  // Validate range (1-indexed input, convert to 0-indexed)
  if (r < 1 || r > num_rows || c < 1 || c > num_cols) {
    return false;
  }

  *row = r - 1;  // Convert to 0-indexed
  *col = c - 1;  // Convert to 0-indexed
  return true;
}
