/*
 * SCPI Analog Multiplexer for ESP32
 *
 * Network-controlled analog multiplexer using CD4051/CD4052/CD4067 CMOS ICs
 * Provides SCPI access over TCP/IP for automated test equipment
 *
 * Supported multiplexer ICs:
 *   CD4051: 8-channel single-ended (3-bit address)
 *   CD4052: Dual 4-channel (2-bit address per mux)
 *   CD4067: 16-channel single-ended (4-bit address)
 *
 * Hardware connections for CD4067 (16-channel, default):
 *   CD4067 pins:
 *     VCC -> 3.3V or 5V
 *     GND -> GND
 *     VEE -> GND (or negative supply for bipolar signals)
 *     S0 -> GPIO 25 (address bit 0, LSB)
 *     S1 -> GPIO 26 (address bit 1)
 *     S2 -> GPIO 27 (address bit 2)
 *     S3 -> GPIO 14 (address bit 3, MSB)
 *     EN -> GPIO 32 (enable, active LOW)
 *     COM -> GPIO 36 (common I/O, ADC for readback)
 *
 *   Signal inputs:
 *     CH0-CH15 -> Connect to analog signals to be switched
 *
 * For CD4051 (8-channel):
 *   Use S0-S2 only (GPIO 25-27), leave S3 unconnected
 *   Channels: CH0-CH7
 *
 * For CD4052 (dual 4-channel):
 *   Use S0-S1 only (GPIO 25-26) for address
 *   EN controls both muxes together
 *   Two separate COM pins - only one monitored on GPIO 36
 *
 * Signal characteristics:
 *   On-resistance: 80-120 Ω typical (CD4051/CD4052), 70 Ω typical (CD4067)
 *   Crosstalk: -60 dB at 1 MHz
 *   Off isolation: -50 dB at 1 MHz
 *   Bandwidth: 40 MHz (analog, -3dB)
 *   Leakage current: <100 pA at 25°C
 *   Operating voltage: 3-15V (digital), ±7.5V (analog)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Multiplexer address pins (S0-S3)
const int s0_pin = 25;  // LSB
const int s1_pin = 26;
const int s2_pin = 27;
const int s3_pin = 14;  // MSB

// Multiplexer enable pin (active LOW)
const int en_pin = 32;

// Common I/O pin for ADC readback
const int adc_pin = 36;  // ADC1_CH0
const int adc_resolution = 12;  // 12-bit ADC = 0-4095
const float adc_vref = 3.3;     // ESP32 reference voltage

// Multiplexer type (default CD4067)
enum MuxType {
  MUX_CD4051,  // 8-channel (3-bit address)
  MUX_CD4052,  // Dual 4-channel (2-bit address)
  MUX_CD4067   // 16-channel (4-bit address)
};

MuxType mux_type = MUX_CD4067;
int max_channels = 16;  // Updated based on mux_type
int selected_channel = 0;
bool mux_enabled = false;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Analog Multiplexer");
  Serial.println("========================");

  // Initialize address pins as outputs
  pinMode(s0_pin, OUTPUT);
  pinMode(s1_pin, OUTPUT);
  pinMode(s2_pin, OUTPUT);
  pinMode(s3_pin, OUTPUT);
  pinMode(en_pin, OUTPUT);

  // Initialize analog input
  pinMode(adc_pin, INPUT);
  analogReadResolution(adc_resolution);
  analogSetAttenuation(ADC_11db);  // Full 0-3.3V range

  // Initialize mux to disabled state, channel 0
  set_mux_channel(0);
  set_mux_enable(false);

  Serial.printf("Multiplexer type: CD4067 (16-channel)\n");
  Serial.printf("Address pins: S0=%d, S1=%d, S2=%d, S3=%d\n", s0_pin, s1_pin, s2_pin, s3_pin);
  Serial.printf("Enable pin: EN=%d (active LOW)\n", en_pin);
  Serial.printf("Common I/O: GPIO %d (ADC)\n", adc_pin);

  // Connect to WiFi
  Serial.printf("\nConnecting to %s", ssid);
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

// Set multiplexer channel (4-bit address for CD4067)
void set_mux_channel(int channel) {
  if (channel < 0 || channel >= max_channels) return;

  // Write address bits to S0-S3 pins
  digitalWrite(s0_pin, (channel & 0x01) ? HIGH : LOW);
  digitalWrite(s1_pin, (channel & 0x02) ? HIGH : LOW);
  digitalWrite(s2_pin, (channel & 0x04) ? HIGH : LOW);
  digitalWrite(s3_pin, (channel & 0x08) ? HIGH : LOW);

  selected_channel = channel;

  // Small delay for mux settling time (~100ns typical, but be conservative)
  delayMicroseconds(10);
}

// Enable or disable multiplexer (EN pin, active LOW)
void set_mux_enable(bool enable) {
  digitalWrite(en_pin, enable ? LOW : HIGH);
  mux_enabled = enable;

  // Small delay for enable propagation
  delayMicroseconds(10);
}

// Read voltage on common I/O pin
float read_adc_voltage() {
  int raw = analogRead(adc_pin);
  return (raw / 4095.0) * adc_vref;
}

// Read raw ADC counts
int read_adc_raw() {
  return analogRead(adc_pin);
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Parse channel number from SCPI command (e.g., ",5" or " 5")
// Returns -1 on error
int parse_channel_number(const char* cmd) {
  const char* comma = strchr(cmd, ',');
  if (!comma) return -1;

  int channel = -1;
  sscanf(comma + 1, "%d", &channel);

  // Validate range based on mux type
  if (channel < 0 || channel >= max_channels) return -1;

  return channel;
}

// Parse enable value from command (e.g., ",0" or ",1")
int parse_enable_value(const char* cmd) {
  const char* comma = strchr(cmd, ',');
  if (!comma) return -1;

  int value = -1;
  sscanf(comma + 1, "%d", &value);

  if (value != 0 && value != 1) return -1;

  return value;
}

// Get mux type name
const char* get_mux_type_name() {
  switch (mux_type) {
    case MUX_CD4051: return "CD4051";
    case MUX_CD4052: return "CD4052";
    case MUX_CD4067: return "CD4067";
    default: return "UNKNOWN";
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

  char response[256];

  // *IDN? - Identification query
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-MUX,1.0,2026\n");
  }

  // *RST - Reset (channel 0, disabled)
  else if (strcmp(cmd, "*RST") == 0) {
    set_mux_channel(0);
    set_mux_enable(false);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // MUX:CHAN,<n> - Select channel
  else if (strncmp(cmd, "MUX:CHAN", 8) == 0) {
    // Check if this is a query
    if (strchr(cmd, '?')) {
      // MUX:CHAN? - Query selected channel
      snprintf(response, sizeof(response), "%d\n", selected_channel);
      send_response(response);
    } else {
      // MUX:CHAN,<n> - Set channel
      int channel = parse_channel_number(cmd);

      if (channel >= 0 && channel < max_channels) {
        set_mux_channel(channel);
        send_response("OK\n");
      } else {
        snprintf(response, sizeof(response), "ERROR: Invalid channel (must be 0-%d for %s)\n",
                 max_channels - 1, get_mux_type_name());
        send_response(response);
      }
    }
  }

  // MUX:EN,<0|1> - Enable/disable mux
  else if (strncmp(cmd, "MUX:EN", 6) == 0) {
    // Check if this is a query
    if (strchr(cmd, '?')) {
      // MUX:EN? - Query enabled state
      send_response(mux_enabled ? "1\n" : "0\n");
    } else {
      // MUX:EN,<0|1> - Set enable state
      int enable = parse_enable_value(cmd);

      if (enable >= 0) {
        set_mux_enable(enable == 1);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid enable value (must be 0 or 1)\n");
      }
    }
  }

  // MUX:READ? - Read ADC on common I/O
  else if (strcmp(cmd, "MUX:READ?") == 0) {
    float voltage = read_adc_voltage();
    snprintf(response, sizeof(response), "%.6f\n", voltage);
    send_response(response);
  }

  // MUX:READ:RAW? - Read raw ADC counts
  else if (strcmp(cmd, "MUX:READ:RAW?") == 0) {
    int raw = read_adc_raw();
    snprintf(response, sizeof(response), "%d\n", raw);
    send_response(response);
  }

  // MUX:TYPE,<CD4051|CD4052|CD4067> - Set mux type
  else if (strncmp(cmd, "MUX:TYPE", 8) == 0) {
    // Check if this is a query
    if (strchr(cmd, '?')) {
      // MUX:TYPE? - Query mux type
      send_response(get_mux_type_name());
      send_response("\n");
    } else {
      // MUX:TYPE,<type> - Set mux type
      const char* comma = strchr(cmd, ',');
      if (comma) {
        const char* type_str = comma + 1;

        // Trim whitespace from type string
        while (*type_str == ' ' || *type_str == '\t') type_str++;

        if (strcmp(type_str, "CD4051") == 0) {
          mux_type = MUX_CD4051;
          max_channels = 8;
          send_response("OK\n");
        } else if (strcmp(type_str, "CD4052") == 0) {
          mux_type = MUX_CD4052;
          max_channels = 4;  // Single mux control (2-bit address)
          send_response("OK\n");
        } else if (strcmp(type_str, "CD4067") == 0) {
          mux_type = MUX_CD4067;
          max_channels = 16;
          send_response("OK\n");
        } else {
          send_response("ERROR: Invalid mux type (must be CD4051, CD4052, or CD4067)\n");
        }

        // Ensure selected channel is valid for new mux type
        if (selected_channel >= max_channels) {
          set_mux_channel(0);
        }
      } else {
        send_response("ERROR: Missing mux type parameter\n");
      }
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
