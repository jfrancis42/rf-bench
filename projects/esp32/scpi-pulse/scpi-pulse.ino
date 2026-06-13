/*
 * SCPI Pulse Generator for ESP32
 *
 * Dual-channel precision pulse generator using hardware timers
 * Control via SCPI commands over TCP/IP
 *
 * Hardware connections:
 *   Output 1 -> GPIO 25 (hardware timer-driven)
 *   Output 2 -> GPIO 26 (hardware timer-driven)
 *
 * Uses ESP32 hardware timers (hw_timer_t) for microsecond-precision pulse generation
 * Supports:
 *   - Frequency: 0.1 Hz to 40 MHz
 *   - Pulse width: 0.1 µs to period/2
 *   - Burst mode: 1-65535 pulses or continuous
 *   - Delay: 0-1 second per pulse
 *   - Independent control per channel
 *   - Software trigger for burst mode
 *
 * Use cases:
 *   - Digital logic testing
 *   - Clock signal generation
 *   - PWM simulation
 *   - Timing stimulus for embedded systems
 *   - Frequency counter calibration
 *   - Trigger source for oscilloscopes
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// GPIO pins for pulse outputs
const int output_pins[2] = {25, 26};

// Hardware timer objects (ESP32 has 4 hardware timers)
hw_timer_t* timers[2] = {NULL, NULL};

// Channel state structure
struct Channel {
  float frequency;        // Hz
  float pulse_width_us;   // microseconds
  uint16_t burst_count;   // 0 = continuous, >0 = burst mode
  float delay_us;         // microseconds delay after each pulse
  bool output_enabled;    // output on/off

  // Runtime state
  volatile uint16_t pulses_remaining;  // decremented by ISR
  volatile bool output_state;          // current pin state
  volatile unsigned long last_edge_time;  // for pulse width timing
};

Channel channels[2];

// Timer prescaler (80 MHz / 80 = 1 MHz tick rate = 1 µs resolution)
const uint16_t timer_prescaler = 80;

// Forward declarations
void IRAM_ATTR timer0_isr();
void IRAM_ATTR timer1_isr();
void update_timer(int ch);

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Pulse Generator");
  Serial.println("====================");

  // Initialize GPIO outputs
  for (int i = 0; i < 2; i++) {
    pinMode(output_pins[i], OUTPUT);
    digitalWrite(output_pins[i], LOW);
  }

  // Initialize channel defaults
  for (int i = 0; i < 2; i++) {
    channels[i].frequency = 1000.0;           // 1 kHz
    channels[i].pulse_width_us = 500.0;       // 500 µs (50% duty cycle at 1 kHz)
    channels[i].burst_count = 0;              // continuous
    channels[i].delay_us = 0.0;               // no delay
    channels[i].output_enabled = false;
    channels[i].pulses_remaining = 0;
    channels[i].output_state = false;
    channels[i].last_edge_time = 0;
  }

  // Initialize hardware timers (but don't start yet)
  timers[0] = timerBegin(0, timer_prescaler, true);  // Timer 0, 1 µs ticks, count up
  timers[1] = timerBegin(1, timer_prescaler, true);  // Timer 1, 1 µs ticks, count up

  timerAttachInterrupt(timers[0], &timer0_isr, true);  // Attach ISR, edge-triggered
  timerAttachInterrupt(timers[1], &timer1_isr, true);

  Serial.printf("Output 1: GPIO %d\n", output_pins[0]);
  Serial.printf("Output 2: GPIO %d\n", output_pins[1]);
  Serial.println("Hardware timers initialized (1 µs resolution)");

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
  Serial.println("Default: 1 kHz, 500 µs pulse width, continuous, outputs disabled");

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

// Timer 0 ISR - channel 1
void IRAM_ATTR timer0_isr() {
  handle_timer_isr(0);
}

// Timer 1 ISR - channel 2
void IRAM_ATTR timer1_isr() {
  handle_timer_isr(1);
}

// Common ISR logic (called from both timer ISRs)
void IRAM_ATTR handle_timer_isr(int ch) {
  Channel* c = &channels[ch];

  // Burst mode: check if we're done
  if (c->burst_count > 0 && c->pulses_remaining == 0) {
    digitalWrite(output_pins[ch], LOW);
    c->output_state = false;
    timerAlarmDisable(timers[ch]);  // Stop timer
    return;
  }

  // Toggle output state
  if (!c->output_state) {
    // Rising edge (start of pulse)
    digitalWrite(output_pins[ch], HIGH);
    c->output_state = true;
    c->last_edge_time = micros();

    // Set alarm for falling edge (pulse_width_us from now)
    timerAlarmWrite(timers[ch], (uint64_t)c->pulse_width_us, false);
    timerAlarmEnable(timers[ch]);

  } else {
    // Falling edge (end of pulse)
    digitalWrite(output_pins[ch], LOW);
    c->output_state = false;

    // Decrement burst counter
    if (c->burst_count > 0) {
      c->pulses_remaining--;
    }

    // Calculate period until next pulse
    float period_us = 1000000.0 / c->frequency;
    float wait_us = period_us - c->pulse_width_us + c->delay_us;

    if (wait_us < 1.0) wait_us = 1.0;  // Minimum 1 µs

    // Set alarm for next rising edge
    timerAlarmWrite(timers[ch], (uint64_t)wait_us, false);
    timerAlarmEnable(timers[ch]);
  }
}

// Update timer configuration (call when frequency/width/delay changes)
void update_timer(int ch) {
  Channel* c = &channels[ch];

  // Stop timer if running
  timerAlarmDisable(timers[ch]);
  timerStop(timers[ch]);
  timerWrite(timers[ch], 0);  // Reset counter

  // Ensure output is low
  digitalWrite(output_pins[ch], LOW);
  c->output_state = false;

  if (!c->output_enabled) {
    return;  // Don't start timer if output disabled
  }

  // Validate pulse width vs period
  float period_us = 1000000.0 / c->frequency;
  if (c->pulse_width_us > period_us * 0.95) {
    c->pulse_width_us = period_us * 0.5;  // Clamp to 50% duty cycle
  }

  // Set burst counter
  if (c->burst_count > 0) {
    c->pulses_remaining = c->burst_count;
  }

  // Calculate initial alarm (time to first rising edge)
  float initial_delay_us = c->delay_us > 0 ? c->delay_us : 10.0;  // Start quickly if no delay

  timerAlarmWrite(timers[ch], (uint64_t)initial_delay_us, false);
  timerAlarmEnable(timers[ch]);
  timerStart(timers[ch]);
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
    send_response("N0GQ,ESP32-SCPI-Pulse,1.0,2026\n");
  }

  // *RST - Reset (stop all outputs, reset to defaults)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < 2; i++) {
      channels[i].output_enabled = false;
      timerAlarmDisable(timers[i]);
      timerStop(timers[i]);
      digitalWrite(output_pins[i], LOW);
      channels[i].frequency = 1000.0;
      channels[i].pulse_width_us = 500.0;
      channels[i].burst_count = 0;
      channels[i].delay_us = 0.0;
    }
    send_response("OK\n");
    Serial.println("Reset: all outputs disabled, defaults restored");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // PULS:FREQ (@n),<hz> - Set frequency
  else if (strncmp(cmd, "PULS:FREQ (@", 12) == 0) {
    int ch = -1;
    float freq = 0.0;
    if (sscanf(cmd, "PULS:FREQ (@%d),%f", &ch, &freq) == 2) {
      ch--;  // Convert to 0-indexed

      if (ch < 0 || ch >= 2) {
        send_response("ERROR: Invalid channel (must be 1 or 2)\n");
      } else if (freq < 0.1 || freq > 40000000.0) {
        send_response("ERROR: Frequency out of range (0.1 Hz - 40 MHz)\n");
      } else {
        channels[ch].frequency = freq;
        if (channels[ch].output_enabled) {
          update_timer(ch);
        }
        send_response("OK\n");
        Serial.printf("Ch %d freq: %.3f Hz\n", ch+1, freq);
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // PULS:FREQ? (@n) - Query frequency
  else if (strncmp(cmd, "PULS:FREQ? (@", 13) == 0) {
    int ch = -1;
    if (sscanf(cmd, "PULS:FREQ? (@%d)", &ch) == 1) {
      ch--;
      if (ch >= 0 && ch < 2) {
        snprintf(response, sizeof(response), "%.6f\n", channels[ch].frequency);
        send_response(response);
      } else {
        send_response("ERROR: Invalid channel\n");
      }
    }
  }

  // PULS:WIDT (@n),<us> - Set pulse width
  else if (strncmp(cmd, "PULS:WIDT (@", 12) == 0) {
    int ch = -1;
    float width_us = 0.0;
    if (sscanf(cmd, "PULS:WIDT (@%d),%f", &ch, &width_us) == 2) {
      ch--;

      if (ch < 0 || ch >= 2) {
        send_response("ERROR: Invalid channel (must be 1 or 2)\n");
      } else if (width_us < 0.1) {
        send_response("ERROR: Pulse width too small (min 0.1 µs)\n");
      } else {
        float period_us = 1000000.0 / channels[ch].frequency;
        if (width_us > period_us / 2.0) {
          send_response("ERROR: Pulse width exceeds half period\n");
        } else {
          channels[ch].pulse_width_us = width_us;
          if (channels[ch].output_enabled) {
            update_timer(ch);
          }
          send_response("OK\n");
          Serial.printf("Ch %d width: %.3f µs\n", ch+1, width_us);
        }
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // PULS:WIDT? (@n) - Query pulse width
  else if (strncmp(cmd, "PULS:WIDT? (@", 13) == 0) {
    int ch = -1;
    if (sscanf(cmd, "PULS:WIDT? (@%d)", &ch) == 1) {
      ch--;
      if (ch >= 0 && ch < 2) {
        snprintf(response, sizeof(response), "%.6f\n", channels[ch].pulse_width_us);
        send_response(response);
      } else {
        send_response("ERROR: Invalid channel\n");
      }
    }
  }

  // PULS:COUN (@n),<count> - Set burst count (0=continuous)
  else if (strncmp(cmd, "PULS:COUN (@", 12) == 0) {
    int ch = -1;
    int count = -1;
    if (sscanf(cmd, "PULS:COUN (@%d),%d", &ch, &count) == 2) {
      ch--;

      if (ch < 0 || ch >= 2) {
        send_response("ERROR: Invalid channel (must be 1 or 2)\n");
      } else if (count < 0 || count > 65535) {
        send_response("ERROR: Count out of range (0-65535)\n");
      } else {
        channels[ch].burst_count = count;
        send_response("OK\n");
        Serial.printf("Ch %d burst: %s\n", ch+1, count == 0 ? "continuous" : String(count).c_str());
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // PULS:COUN? (@n) - Query burst count
  else if (strncmp(cmd, "PULS:COUN? (@", 13) == 0) {
    int ch = -1;
    if (sscanf(cmd, "PULS:COUN? (@%d)", &ch) == 1) {
      ch--;
      if (ch >= 0 && ch < 2) {
        snprintf(response, sizeof(response), "%d\n", channels[ch].burst_count);
        send_response(response);
      } else {
        send_response("ERROR: Invalid channel\n");
      }
    }
  }

  // PULS:DEL (@n),<us> - Set delay
  else if (strncmp(cmd, "PULS:DEL (@", 11) == 0) {
    int ch = -1;
    float delay_us = 0.0;
    if (sscanf(cmd, "PULS:DEL (@%d),%f", &ch, &delay_us) == 2) {
      ch--;

      if (ch < 0 || ch >= 2) {
        send_response("ERROR: Invalid channel (must be 1 or 2)\n");
      } else if (delay_us < 0.0 || delay_us > 1000000.0) {
        send_response("ERROR: Delay out of range (0-1000000 µs)\n");
      } else {
        channels[ch].delay_us = delay_us;
        if (channels[ch].output_enabled) {
          update_timer(ch);
        }
        send_response("OK\n");
        Serial.printf("Ch %d delay: %.3f µs\n", ch+1, delay_us);
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // PULS:DEL? (@n) - Query delay
  else if (strncmp(cmd, "PULS:DEL? (@", 12) == 0) {
    int ch = -1;
    if (sscanf(cmd, "PULS:DEL? (@%d)", &ch) == 1) {
      ch--;
      if (ch >= 0 && ch < 2) {
        snprintf(response, sizeof(response), "%.6f\n", channels[ch].delay_us);
        send_response(response);
      } else {
        send_response("ERROR: Invalid channel\n");
      }
    }
  }

  // PULS:OUTP (@n),<0|1> - Enable/disable output
  else if (strncmp(cmd, "PULS:OUTP (@", 12) == 0) {
    int ch = -1;
    int state = -1;
    if (sscanf(cmd, "PULS:OUTP (@%d),%d", &ch, &state) == 2) {
      ch--;

      if (ch < 0 || ch >= 2) {
        send_response("ERROR: Invalid channel (must be 1 or 2)\n");
      } else if (state != 0 && state != 1) {
        send_response("ERROR: Invalid state (must be 0 or 1)\n");
      } else {
        channels[ch].output_enabled = (state == 1);

        if (channels[ch].output_enabled) {
          update_timer(ch);
        } else {
          timerAlarmDisable(timers[ch]);
          timerStop(timers[ch]);
          digitalWrite(output_pins[ch], LOW);
          channels[ch].output_state = false;
        }

        send_response("OK\n");
        Serial.printf("Ch %d output: %s\n", ch+1, state ? "ON" : "OFF");
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // PULS:OUTP? (@n) - Query output state
  else if (strncmp(cmd, "PULS:OUTP? (@", 13) == 0) {
    int ch = -1;
    if (sscanf(cmd, "PULS:OUTP? (@%d)", &ch) == 1) {
      ch--;
      if (ch >= 0 && ch < 2) {
        snprintf(response, sizeof(response), "%d\n", channels[ch].output_enabled ? 1 : 0);
        send_response(response);
      } else {
        send_response("ERROR: Invalid channel\n");
      }
    }
  }

  // PULS:TRIG (@n) - Software trigger (restart burst)
  else if (strncmp(cmd, "PULS:TRIG (@", 12) == 0) {
    int ch = -1;
    if (sscanf(cmd, "PULS:TRIG (@%d)", &ch) == 1) {
      ch--;

      if (ch < 0 || ch >= 2) {
        send_response("ERROR: Invalid channel (must be 1 or 2)\n");
      } else if (!channels[ch].output_enabled) {
        send_response("ERROR: Output must be enabled first\n");
      } else {
        // Restart timer (for burst mode, resets pulse counter)
        update_timer(ch);
        send_response("OK\n");
        Serial.printf("Ch %d triggered\n", ch+1);
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
