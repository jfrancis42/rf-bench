/*
 * SCPI Relay Controller for ESP32
 *
 * Controls 4-channel relay board via SCPI commands over TCP/IP
 * Compatible with typical cheap Amazon/AliExpress relay modules
 *
 * Hardware connections:
 *   Relay outputs (active-low):
 *     GPIO 25 -> Relay 1 (IN1)
 *     GPIO 26 -> Relay 2 (IN2)
 *     GPIO 27 -> Relay 3 (IN3)
 *     GPIO 14 -> Relay 4 (IN4)
 *
 *   Digital inputs (3.3V logic):
 *     GPIO 32 -> Digital Input 1
 *     GPIO 33 -> Digital Input 2
 *     GPIO 35 -> Digital Input 3
 *     GPIO 34 -> Digital Input 4
 *
 *   Analog input (0-3.3V):
 *     GPIO 36 -> Analog Input (ADC1_CH0)
 *
 * Note: Most cheap relay boards are ACTIVE LOW (relay on when pin LOW)
 * Digital inputs have internal pull-down enabled (read HIGH when connected to 3.3V)
 * Analog input: 12-bit ADC (0-4095 raw counts = 0-3.3V)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Relay GPIO pins
const int relay_pins[4] = {25, 26, 27, 14};
const int num_relays = 4;

// Relay states (true = on/energized, false = off/de-energized)
bool relay_states[4] = {false, false, false, false};

// Most cheap relay boards are active-low (LOW = relay on)
// Set to true if your board is active-high (HIGH = relay on)
const bool active_high = false;

// Digital input GPIO pins (input-only pins: 34, 35, 36, 39 are input-only)
const int digital_input_pins[4] = {32, 33, 35, 34};
const int num_digital_inputs = 4;

// Analog input GPIO pin (ADC1_CH0)
const int analog_input_pin = 36;
const int adc_resolution = 12;  // 12-bit ADC = 0-4095
const float adc_vref = 3.3;     // ESP32 reference voltage

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Relay Controller");
  Serial.println("=====================");

  // Initialize relay pins
  for (int i = 0; i < num_relays; i++) {
    pinMode(relay_pins[i], OUTPUT);
    set_relay_physical(i, false);  // All relays off at startup
  }

  // Initialize digital input pins with pull-down resistors
  for (int i = 0; i < num_digital_inputs; i++) {
    pinMode(digital_input_pins[i], INPUT_PULLDOWN);
  }

  // Initialize analog input
  pinMode(analog_input_pin, INPUT);
  analogReadResolution(adc_resolution);
  analogSetAttenuation(ADC_11db);  // Full 0-3.3V range

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

      // Echo character for debugging (optional)
      // Serial.write(c);

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

// Set physical relay state (handles active-high/active-low logic)
void set_relay_physical(int relay, bool state) {
  if (relay < 0 || relay >= num_relays) return;

  bool pin_state = active_high ? state : !state;
  digitalWrite(relay_pins[relay], pin_state ? HIGH : LOW);
  relay_states[relay] = state;
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
    send_response("N0GQ,ESP32-SCPI-Relay,1.0,2026\n");
  }

  // *RST - Reset (all relays off)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < num_relays; i++) {
      set_relay_physical(i, false);
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error (always none for this simple device)
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // ROUTE:CLOSE (@n) - Close relay n (turn on)
  else if (strncmp(cmd, "ROUT:CLOS", 9) == 0 || strncmp(cmd, "ROUTE:CLOSE", 11) == 0) {
    int relay = parse_relay_number(cmd);
    if (relay >= 0 && relay < num_relays) {
      set_relay_physical(relay, true);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid relay number\n");
    }
  }

  // ROUTE:OPEN (@n) - Open relay n (turn off)
  else if (strncmp(cmd, "ROUT:OPEN", 9) == 0 || strncmp(cmd, "ROUTE:OPEN", 10) == 0) {
    int relay = parse_relay_number(cmd);
    if (relay >= 0 && relay < num_relays) {
      set_relay_physical(relay, false);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid relay number\n");
    }
  }

  // ROUTE:CLOSE:STATE? (@n) - Query relay state
  else if (strncmp(cmd, "ROUT:CLOS:STAT", 14) == 0 || strncmp(cmd, "ROUTE:CLOSE:STATE", 17) == 0) {
    int relay = parse_relay_number(cmd);
    if (relay >= 0 && relay < num_relays) {
      send_response(relay_states[relay] ? "1\n" : "0\n");
    } else {
      send_response("ERROR: Invalid relay number\n");
    }
  }

  // ROUTE:CLOSE:ALL - Close all relays
  else if (strcmp(cmd, "ROUT:CLOS:ALL") == 0 || strcmp(cmd, "ROUTE:CLOSE:ALL") == 0) {
    for (int i = 0; i < num_relays; i++) {
      set_relay_physical(i, true);
    }
    send_response("OK\n");
  }

  // ROUTE:OPEN:ALL - Open all relays
  else if (strcmp(cmd, "ROUT:OPEN:ALL") == 0 || strcmp(cmd, "ROUTE:OPEN:ALL") == 0) {
    for (int i = 0; i < num_relays; i++) {
      set_relay_physical(i, false);
    }
    send_response("OK\n");
  }

  // MEAS:DIG? (@n) - Read digital input n
  else if (strncmp(cmd, "MEAS:DIG", 8) == 0 || strncmp(cmd, "MEASURE:DIGITAL", 15) == 0) {
    int input_num = parse_relay_number(cmd);  // Reuse same (@n) parsing
    if (input_num >= 0 && input_num < num_digital_inputs) {
      bool state = digitalRead(digital_input_pins[input_num]);
      send_response(state ? "1\n" : "0\n");
    } else {
      send_response("ERROR: Invalid digital input number\n");
    }
  }

  // MEAS:DIG:ALL? - Read all digital inputs
  else if (strcmp(cmd, "MEAS:DIG:ALL?") == 0 || strcmp(cmd, "MEASURE:DIGITAL:ALL?") == 0) {
    char response[32];
    snprintf(response, sizeof(response), "%d,%d,%d,%d\n",
             digitalRead(digital_input_pins[0]) ? 1 : 0,
             digitalRead(digital_input_pins[1]) ? 1 : 0,
             digitalRead(digital_input_pins[2]) ? 1 : 0,
             digitalRead(digital_input_pins[3]) ? 1 : 0);
    send_response(response);
  }

  // MEAS:VOLT? - Read analog input voltage
  else if (strcmp(cmd, "MEAS:VOLT?") == 0 || strcmp(cmd, "MEASURE:VOLTAGE?") == 0) {
    int raw = analogRead(analog_input_pin);
    float voltage = (raw / 4095.0) * adc_vref;
    char response[32];
    snprintf(response, sizeof(response), "%.4f\n", voltage);
    send_response(response);
  }

  // MEAS:VOLT:RAW? - Read analog input raw ADC counts
  else if (strcmp(cmd, "MEAS:VOLT:RAW?") == 0 || strcmp(cmd, "MEASURE:VOLTAGE:RAW?") == 0) {
    int raw = analogRead(analog_input_pin);
    char response[16];
    snprintf(response, sizeof(response), "%d\n", raw);
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}

// Parse relay number from SCPI command (e.g., "(@1)" or "(@4)")
int parse_relay_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int relay = -1;
  sscanf(at_sign, "@%d", &relay);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return relay - 1;
}
