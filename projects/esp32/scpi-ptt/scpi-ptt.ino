/*
 * SCPI PTT Controller for ESP32
 *
 * Push-to-talk (PTT) and VOX controller via SCPI commands over TCP/IP
 * Suitable for radio remote control, repeater control, and automated testing
 *
 * Hardware connections:
 *   PTT output (open-drain/relay):
 *     GPIO 25 -> PTT control (active-low, suitable for relay or open-collector)
 *
 *   COS input (carrier detect/squelch):
 *     GPIO 26 -> Carrier Operated Squelch input (3.3V logic)
 *
 *   VOX input (audio level detect):
 *     GPIO 36 -> Audio level input (0-3.3V, ADC1_CH0)
 *
 *   Optional relay for amplifier control:
 *     GPIO 27 -> Amplifier relay (active-low)
 *
 * VOX (Voice Operated Transmit):
 *   - Monitors audio level on GPIO 36
 *   - When level exceeds threshold, activates PTT automatically
 *   - Configurable threshold (0-100 scale, maps to 0-3.3V)
 *   - Can be enabled/disabled via SCPI
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// GPIO pin assignments
const int ptt_pin = 25;       // PTT output (open-drain/relay)
const int cos_pin = 26;       // COS input (carrier detect)
const int vox_pin = 36;       // VOX input (audio level, ADC)
const int amp_pin = 27;       // Amplifier relay (optional)

// PTT state
bool ptt_active = false;

// Amplifier relay state
bool amp_active = false;

// Most relay boards and PTT circuits are active-low (LOW = TX)
// Set to true if your PTT circuit is active-high (HIGH = TX)
const bool ptt_active_high = false;
const bool amp_active_high = false;

// VOX configuration
bool vox_enabled = false;
int vox_threshold = 30;       // 0-100 scale (30 = moderate sensitivity)
unsigned long vox_hangtime = 1000;  // VOX hang time in ms
unsigned long vox_last_trigger = 0;

// ADC configuration
const int adc_resolution = 12;      // 12-bit ADC = 0-4095
const float adc_vref = 3.3;         // ESP32 reference voltage

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI PTT Controller");
  Serial.println("===================");

  // Initialize PTT output (default: RX mode)
  pinMode(ptt_pin, OUTPUT);
  set_ptt_physical(false);

  // Initialize amplifier output (default: off)
  pinMode(amp_pin, OUTPUT);
  set_amp_physical(false);

  // Initialize COS input with pull-down resistor
  pinMode(cos_pin, INPUT_PULLDOWN);

  // Initialize VOX/audio level input
  pinMode(vox_pin, INPUT);
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
  Serial.println("PTT: RX mode (default)");
  Serial.printf("VOX: disabled (threshold: %d%%)\n", vox_threshold);

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

  // VOX auto-trigger logic
  if (vox_enabled) {
    int audio_level = read_vox_level();

    if (audio_level >= vox_threshold) {
      if (!ptt_active) {
        Serial.printf("VOX triggered (level: %d, threshold: %d)\n", audio_level, vox_threshold);
        set_ptt_physical(true);
      }
      vox_last_trigger = millis();
    } else {
      // VOX hang time: keep PTT active for a period after audio drops
      if (ptt_active && (millis() - vox_last_trigger > vox_hangtime)) {
        Serial.println("VOX released (hang time expired)");
        set_ptt_physical(false);
      }
    }
  }
}

// Set physical PTT state (handles active-high/active-low logic)
void set_ptt_physical(bool state) {
  bool pin_state = ptt_active_high ? state : !state;
  digitalWrite(ptt_pin, pin_state ? HIGH : LOW);
  ptt_active = state;
}

// Set physical amplifier relay state
void set_amp_physical(bool state) {
  bool pin_state = amp_active_high ? state : !state;
  digitalWrite(amp_pin, pin_state ? HIGH : LOW);
  amp_active = state;
}

// Read VOX audio level as 0-100 scale
int read_vox_level() {
  int raw = analogRead(vox_pin);
  // Map 12-bit ADC (0-4095) to 0-100 scale
  return map(raw, 0, 4095, 0, 100);
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

  char response[128];

  // *IDN? - Identification query
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-PTT,1.0,2026\n");
  }

  // *RST - Reset (PTT off, VOX disabled)
  else if (strcmp(cmd, "*RST") == 0) {
    set_ptt_physical(false);
    set_amp_physical(false);
    vox_enabled = false;
    vox_threshold = 30;
    send_response("OK\n");
    Serial.println("Reset: PTT off, VOX disabled");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // PTT,<0|1> - Set PTT state
  else if (strncmp(cmd, "PTT,", 4) == 0) {
    int state = -1;
    sscanf(cmd + 4, "%d", &state);

    if (state == 0 || state == 1) {
      set_ptt_physical(state == 1);
      send_response("OK\n");
      Serial.printf("PTT: %s\n", state ? "TX" : "RX");
    } else {
      send_response("ERROR: Invalid PTT state (must be 0 or 1)\n");
    }
  }

  // PTT? - Query PTT state
  else if (strcmp(cmd, "PTT?") == 0) {
    snprintf(response, sizeof(response), "%d\n", ptt_active ? 1 : 0);
    send_response(response);
  }

  // COS? - Query carrier detect input
  else if (strcmp(cmd, "COS?") == 0) {
    bool cos_state = digitalRead(cos_pin);
    snprintf(response, sizeof(response), "%d\n", cos_state ? 1 : 0);
    send_response(response);
  }

  // VOX:LEV? - Read audio level (0-100)
  else if (strcmp(cmd, "VOX:LEV?") == 0 || strcmp(cmd, "VOX:LEVEL?") == 0) {
    int level = read_vox_level();
    snprintf(response, sizeof(response), "%d\n", level);
    send_response(response);
  }

  // VOX:THRE,<0-100> - Set VOX threshold
  else if (strncmp(cmd, "VOX:THRE,", 9) == 0 || strncmp(cmd, "VOX:THRESHOLD,", 14) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int threshold = -1;
      sscanf(comma + 1, "%d", &threshold);

      if (threshold >= 0 && threshold <= 100) {
        vox_threshold = threshold;
        send_response("OK\n");
        Serial.printf("VOX threshold: %d%%\n", vox_threshold);
      } else {
        send_response("ERROR: Invalid threshold (must be 0-100)\n");
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // VOX:THRE? - Query VOX threshold
  else if (strcmp(cmd, "VOX:THRE?") == 0 || strcmp(cmd, "VOX:THRESHOLD?") == 0) {
    snprintf(response, sizeof(response), "%d\n", vox_threshold);
    send_response(response);
  }

  // VOX:EN,<0|1> - Enable/disable auto VOX
  else if (strncmp(cmd, "VOX:EN,", 7) == 0 || strncmp(cmd, "VOX:ENABLE,", 11) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int enable = -1;
      sscanf(comma + 1, "%d", &enable);

      if (enable == 0 || enable == 1) {
        vox_enabled = (enable == 1);

        // If disabling VOX, release PTT if it was VOX-triggered
        if (!vox_enabled && ptt_active) {
          set_ptt_physical(false);
        }

        send_response("OK\n");
        Serial.printf("VOX: %s\n", vox_enabled ? "enabled" : "disabled");
      } else {
        send_response("ERROR: Invalid enable state (must be 0 or 1)\n");
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // VOX:EN? - Query VOX enabled state
  else if (strcmp(cmd, "VOX:EN?") == 0 || strcmp(cmd, "VOX:ENABLE?") == 0) {
    snprintf(response, sizeof(response), "%d\n", vox_enabled ? 1 : 0);
    send_response(response);
  }

  // AMP,<0|1> - Set amplifier relay state
  else if (strncmp(cmd, "AMP,", 4) == 0) {
    int state = -1;
    sscanf(cmd + 4, "%d", &state);

    if (state == 0 || state == 1) {
      set_amp_physical(state == 1);
      send_response("OK\n");
      Serial.printf("AMP: %s\n", state ? "on" : "off");
    } else {
      send_response("ERROR: Invalid AMP state (must be 0 or 1)\n");
    }
  }

  // AMP? - Query amplifier relay state
  else if (strcmp(cmd, "AMP?") == 0) {
    snprintf(response, sizeof(response), "%d\n", amp_active ? 1 : 0);
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
