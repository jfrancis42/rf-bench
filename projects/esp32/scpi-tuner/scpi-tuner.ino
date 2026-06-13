/*
 * SCPI Antenna Tuner Controller for ESP32
 *
 * Controls L/C matching network via stepper motors or relays with optional SWR feedback
 * Provides SCPI access over TCP/IP for automated antenna tuning
 *
 * Hardware connections:
 *   Inductor Control (stepper motor or relay-switched):
 *     STEP -> GPIO 25 (if stepper)
 *     DIR  -> GPIO 26 (if stepper)
 *
 *   Capacitor Control (stepper motor or relay-switched):
 *     STEP -> GPIO 27 (if stepper)
 *     DIR  -> GPIO 14 (if stepper)
 *
 *   Optional SWR Sensor (for auto-tune):
 *     FWD  -> GPIO 36 (ADC1_CH0) - forward power detector
 *     REF  -> GPIO 39 (ADC1_CH3) - reflected power detector
 *
 * Control modes:
 *   - Manual position control (TUN:IND,<pos> / TUN:CAP,<pos>)
 *   - Auto-tune via grid search (TUN:AUTO) - requires SWR sensor
 *   - Save/recall positions to/from EEPROM slots (TUN:SAVE,<slot> / TUN:RECA,<slot>)
 *
 * Position range: 0-255 for both L and C
 * EEPROM slots: 10 tuning presets
 *
 * Use cases:
 *   - Automated antenna matching for multi-band operation
 *   - Remote tuning for unattended stations
 *   - Integration with transceiver CAT control
 *   - Magnetic loop antenna tuning
 */

#include <WiFi.h>
#include <Preferences.h>  // ESP32 NVS (non-volatile storage)

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Motor/relay GPIO pins
const int l_step_pin = 25;
const int l_dir_pin = 26;
const int c_step_pin = 27;
const int c_dir_pin = 14;

// Optional SWR sensor pins (ADC1 only - ADC2 conflicts with WiFi)
const int fwd_adc_pin = 36;  // GPIO 36 = ADC1_CH0
const int ref_adc_pin = 39;  // GPIO 39 = ADC1_CH3

// Position limits
const int max_position = 255;

// Current positions
int l_position = 0;
int c_position = 0;

// Target positions (for non-blocking motion)
int l_target = 0;
int c_target = 0;
bool l_moving = false;
bool c_moving = false;

// Timing for step generation
unsigned long l_last_step_us = 0;
unsigned long c_last_step_us = 0;
const unsigned long step_delay_us = 2000;  // 2ms between steps = 500 steps/sec
const unsigned long step_pulse_us = 2;     // 2µs pulse width

// EEPROM storage slots
const int max_slots = 10;
Preferences preferences;

// SWR sensor enabled flag
bool swr_enabled = false;
const int adc_samples = 10;  // Samples to average

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Antenna Tuner Controller");
  Serial.println("==============================");

  // Initialize GPIO pins
  pinMode(l_step_pin, OUTPUT);
  pinMode(l_dir_pin, OUTPUT);
  pinMode(c_step_pin, OUTPUT);
  pinMode(c_dir_pin, OUTPUT);

  digitalWrite(l_step_pin, LOW);
  digitalWrite(l_dir_pin, LOW);
  digitalWrite(c_step_pin, LOW);
  digitalWrite(c_dir_pin, LOW);

  Serial.printf("Inductor:  STEP=%d, DIR=%d\n", l_step_pin, l_dir_pin);
  Serial.printf("Capacitor: STEP=%d, DIR=%d\n", c_step_pin, c_dir_pin);

  // Check if SWR sensor is present (optional)
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);  // 0-3.9V range

  // Simple presence detection: read ADC and see if it's not stuck at 0 or max
  int fwd_test = analogRead(fwd_adc_pin);
  int ref_test = analogRead(ref_adc_pin);

  if (fwd_test > 10 && fwd_test < 4085) {
    swr_enabled = true;
    Serial.printf("\nSWR sensor detected: FWD on GPIO %d, REF on GPIO %d\n",
                  fwd_adc_pin, ref_adc_pin);
  } else {
    Serial.println("\nNo SWR sensor detected (auto-tune disabled)");
    Serial.println("Connect FWD to GPIO 36 and REF to GPIO 39 for auto-tune support");
  }

  // Load last position from NVS
  preferences.begin("tuner", true);  // Read-only
  l_position = preferences.getInt("l_pos", 0);
  c_position = preferences.getInt("c_pos", 0);
  preferences.end();

  l_target = l_position;
  c_target = c_position;

  Serial.printf("\nLast position: L=%d, C=%d\n", l_position, c_position);

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
  // Update motor positions (non-blocking)
  update_motors();

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

// Update motor positions (non-blocking step generation)
void update_motors() {
  unsigned long now = micros();

  // Update inductor position
  if (l_moving && now - l_last_step_us >= step_delay_us) {
    if (l_position != l_target) {
      bool step_forward = l_target > l_position;
      digitalWrite(l_dir_pin, step_forward ? HIGH : LOW);
      delayMicroseconds(1);  // DIR setup time

      digitalWrite(l_step_pin, HIGH);
      delayMicroseconds(step_pulse_us);
      digitalWrite(l_step_pin, LOW);

      l_position += step_forward ? 1 : -1;
      l_last_step_us = now;
    } else {
      l_moving = false;
      Serial.printf("Inductor reached target: %d\n", l_position);
    }
  }

  // Update capacitor position
  if (c_moving && now - c_last_step_us >= step_delay_us) {
    if (c_position != c_target) {
      bool step_forward = c_target > c_position;
      digitalWrite(c_dir_pin, step_forward ? HIGH : LOW);
      delayMicroseconds(1);  // DIR setup time

      digitalWrite(c_step_pin, HIGH);
      delayMicroseconds(step_pulse_us);
      digitalWrite(c_step_pin, LOW);

      c_position += step_forward ? 1 : -1;
      c_last_step_us = now;
    } else {
      c_moving = false;
      Serial.printf("Capacitor reached target: %d\n", c_position);
    }
  }
}

// Set inductor position
void set_l_position(int pos) {
  if (pos < 0) pos = 0;
  if (pos > max_position) pos = max_position;

  l_target = pos;
  l_moving = true;

  Serial.printf("Inductor moving: %d -> %d\n", l_position, l_target);
}

// Set capacitor position
void set_c_position(int pos) {
  if (pos < 0) pos = 0;
  if (pos > max_position) pos = max_position;

  c_target = pos;
  c_moving = true;

  Serial.printf("Capacitor moving: %d -> %d\n", c_position, c_target);
}

// Wait for motors to stop moving
void wait_for_stop() {
  while (l_moving || c_moving) {
    update_motors();
    delay(1);
  }
}

// Read raw ADC value with averaging
int read_adc(int pin) {
  long sum = 0;
  for (int i = 0; i < adc_samples; i++) {
    sum += analogRead(pin);
    delayMicroseconds(100);
  }
  return sum / adc_samples;
}

// Read SWR (simple ratio calculation - assumes calibrated sensors)
float read_swr() {
  if (!swr_enabled) return 99.9;

  int fwd_raw = read_adc(fwd_adc_pin);
  int ref_raw = read_adc(ref_adc_pin);

  // Simple voltage-based SWR (assumes linear detectors)
  // For accurate results, calibrate with known power levels
  if (fwd_raw < 100) return 99.9;  // No forward power
  if (ref_raw < 10) return 1.0;    // No reflected power

  // Convert to voltage ratio
  float fwd_v = fwd_raw / 4095.0;
  float ref_v = ref_raw / 4095.0;

  // Reflection coefficient: Γ = V_ref / V_fwd
  float gamma = ref_v / fwd_v;
  if (gamma >= 1.0) return 99.9;

  // SWR = (1 + Γ) / (1 - Γ)
  float swr = (1.0 + gamma) / (1.0 - gamma);

  if (swr < 1.0) swr = 1.0;
  if (swr > 99.9) swr = 99.9;

  return swr;
}

// Auto-tune via grid search
void auto_tune() {
  if (!swr_enabled) {
    send_response("ERROR: No SWR sensor detected\n");
    return;
  }

  Serial.println("Starting auto-tune (grid search)...");
  send_response("AUTO-TUNE STARTED\n");

  float best_swr = 99.9;
  int best_l = l_position;
  int best_c = c_position;

  // Coarse grid search: 16x16 = 256 points
  const int coarse_step = 16;

  for (int l = 0; l <= max_position; l += coarse_step) {
    set_l_position(l);
    wait_for_stop();

    for (int c = 0; c <= max_position; c += coarse_step) {
      set_c_position(c);
      wait_for_stop();
      delay(50);  // Settle time

      float swr = read_swr();

      if (swr < best_swr) {
        best_swr = swr;
        best_l = l;
        best_c = c;
        Serial.printf("New best: L=%d, C=%d, SWR=%.2f\n", l, c, swr);
      }

      // Early exit if perfect match found
      if (swr < 1.1) {
        Serial.println("Excellent match found, stopping search");
        goto fine_tune;
      }
    }
  }

fine_tune:
  // Fine-tune around best position
  Serial.printf("Fine-tuning around L=%d, C=%d\n", best_l, best_c);

  for (int l = best_l - coarse_step; l <= best_l + coarse_step; l += 2) {
    if (l < 0 || l > max_position) continue;

    set_l_position(l);
    wait_for_stop();

    for (int c = best_c - coarse_step; c <= best_c + coarse_step; c += 2) {
      if (c < 0 || c > max_position) continue;

      set_c_position(c);
      wait_for_stop();
      delay(50);

      float swr = read_swr();

      if (swr < best_swr) {
        best_swr = swr;
        best_l = l;
        best_c = c;
        Serial.printf("Fine-tune best: L=%d, C=%d, SWR=%.2f\n", l, c, swr);
      }
    }
  }

  // Move to best position
  set_l_position(best_l);
  set_c_position(best_c);
  wait_for_stop();

  char response[128];
  snprintf(response, sizeof(response), "AUTO-TUNE COMPLETE: L=%d, C=%d, SWR=%.2f\n",
           best_l, best_c, best_swr);
  send_response(response);
  Serial.print(response);
}

// Save current position to slot
void save_position(int slot) {
  if (slot < 0 || slot >= max_slots) {
    send_response("ERROR: Invalid slot (0-9)\n");
    return;
  }

  preferences.begin("tuner", false);  // Read-write
  char key_l[16], key_c[16];
  snprintf(key_l, sizeof(key_l), "slot%d_l", slot);
  snprintf(key_c, sizeof(key_c), "slot%d_c", slot);

  preferences.putInt(key_l, l_position);
  preferences.putInt(key_c, c_position);
  preferences.end();

  Serial.printf("Saved to slot %d: L=%d, C=%d\n", slot, l_position, c_position);
  send_response("OK\n");
}

// Recall position from slot
void recall_position(int slot) {
  if (slot < 0 || slot >= max_slots) {
    send_response("ERROR: Invalid slot (0-9)\n");
    return;
  }

  preferences.begin("tuner", true);  // Read-only
  char key_l[16], key_c[16];
  snprintf(key_l, sizeof(key_l), "slot%d_l", slot);
  snprintf(key_c, sizeof(key_c), "slot%d_c", slot);

  int saved_l = preferences.getInt(key_l, -1);
  int saved_c = preferences.getInt(key_c, -1);
  preferences.end();

  if (saved_l < 0 || saved_c < 0) {
    send_response("ERROR: Slot empty\n");
    return;
  }

  set_l_position(saved_l);
  set_c_position(saved_c);

  char response[64];
  snprintf(response, sizeof(response), "OK: Recalled L=%d, C=%d from slot %d\n",
           saved_l, saved_c, slot);
  send_response(response);
  Serial.print(response);
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
    send_response("N0GQ,ESP32-SCPI-Tuner,1.0,2026\n");
  }

  // *RST - Reset (home both to position 0)
  else if (strcmp(cmd, "*RST") == 0) {
    set_l_position(0);
    set_c_position(0);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // TUN:IND,<pos> - Set inductor position
  else if (strncmp(cmd, "TUN:IND,", 8) == 0) {
    int pos;
    if (sscanf(cmd + 8, "%d", &pos) == 1) {
      if (pos >= 0 && pos <= max_position) {
        set_l_position(pos);
        send_response("OK\n");
      } else {
        send_response("ERROR: Position must be 0-255\n");
      }
    } else {
      send_response("ERROR: Invalid position\n");
    }
  }

  // TUN:IND? - Query inductor position
  else if (strcmp(cmd, "TUN:IND?") == 0 || strcmp(cmd, "TUN:INDUCTOR?") == 0) {
    snprintf(response, sizeof(response), "%d\n", l_position);
    send_response(response);
  }

  // TUN:CAP,<pos> - Set capacitor position
  else if (strncmp(cmd, "TUN:CAP,", 8) == 0) {
    int pos;
    if (sscanf(cmd + 8, "%d", &pos) == 1) {
      if (pos >= 0 && pos <= max_position) {
        set_c_position(pos);
        send_response("OK\n");
      } else {
        send_response("ERROR: Position must be 0-255\n");
      }
    } else {
      send_response("ERROR: Invalid position\n");
    }
  }

  // TUN:CAP? - Query capacitor position
  else if (strcmp(cmd, "TUN:CAP?") == 0 || strcmp(cmd, "TUN:CAPACITOR?") == 0) {
    snprintf(response, sizeof(response), "%d\n", c_position);
    send_response(response);
  }

  // TUN:AUTO - Auto-tune via grid search
  else if (strcmp(cmd, "TUN:AUTO") == 0) {
    auto_tune();
  }

  // TUN:SWR? - Query current SWR
  else if (strcmp(cmd, "TUN:SWR?") == 0) {
    if (!swr_enabled) {
      send_response("ERROR: No SWR sensor\n");
    } else {
      float swr = read_swr();
      snprintf(response, sizeof(response), "%.2f\n", swr);
      send_response(response);
    }
  }

  // TUN:SAVE,<slot> - Save current position to EEPROM slot
  else if (strncmp(cmd, "TUN:SAVE,", 9) == 0 || strncmp(cmd, "TUN:SAV,", 8) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int slot;
      if (sscanf(comma + 1, "%d", &slot) == 1) {
        save_position(slot);
      } else {
        send_response("ERROR: Invalid slot number\n");
      }
    } else {
      send_response("ERROR: Missing slot number\n");
    }
  }

  // TUN:RECA,<slot> - Recall position from EEPROM slot
  else if (strncmp(cmd, "TUN:RECA,", 9) == 0 || strncmp(cmd, "TUN:RECALL,", 11) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int slot;
      if (sscanf(comma + 1, "%d", &slot) == 1) {
        recall_position(slot);
      } else {
        send_response("ERROR: Invalid slot number\n");
      }
    } else {
      send_response("ERROR: Missing slot number\n");
    }
  }

  // TUN:STAT? - Query tuning status (moving or stopped)
  else if (strcmp(cmd, "TUN:STAT?") == 0 || strcmp(cmd, "TUN:STATUS?") == 0) {
    if (l_moving || c_moving) {
      send_response("MOVING\n");
    } else {
      send_response("STOPPED\n");
    }
  }

  // ADC:FWD? - Query raw forward power ADC
  else if (strcmp(cmd, "ADC:FWD?") == 0) {
    if (!swr_enabled) {
      send_response("ERROR: No SWR sensor\n");
    } else {
      int raw = read_adc(fwd_adc_pin);
      snprintf(response, sizeof(response), "%d\n", raw);
      send_response(response);
    }
  }

  // ADC:REF? - Query raw reflected power ADC
  else if (strcmp(cmd, "ADC:REF?") == 0) {
    if (!swr_enabled) {
      send_response("ERROR: No SWR sensor\n");
    } else {
      int raw = read_adc(ref_adc_pin);
      snprintf(response, sizeof(response), "%d\n", raw);
      send_response(response);
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
