/*
 * SCPI PWM Generator for ESP32
 *
 * 8-channel PWM generator controlled via SCPI commands over TCP/IP
 * Uses ESP32 LED PWM peripheral for hardware-generated PWM signals
 *
 * Hardware connections:
 *   PWM Channel 1 -> GPIO 25
 *   PWM Channel 2 -> GPIO 26
 *   PWM Channel 3 -> GPIO 27
 *   PWM Channel 4 -> GPIO 14
 *   PWM Channel 5 -> GPIO 32
 *   PWM Channel 6 -> GPIO 33
 *   PWM Channel 7 -> GPIO 23
 *   PWM Channel 8 -> GPIO 19
 *
 * All outputs are 3.3V logic level.
 * Frequency range: 1 Hz - 40 kHz
 * Duty cycle: 0-100% (floating point precision)
 *
 * Use cases:
 * - PWM signal generation for testing/characterization
 * - LED dimming / brightness control
 * - Motor speed control (via driver)
 * - Analog voltage simulation (with low-pass filter)
 * - Clock generation for digital circuits
 * - Fan speed control
 * - Heater control (via SSR)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// PWM configuration
const int num_channels = 8;
const int pwm_pins[num_channels] = {25, 26, 27, 14, 32, 33, 23, 19};

// PWM state for each channel
struct PWMChannel {
  int pin;              // GPIO pin
  int ledc_channel;     // LED PWM channel (0-15)
  float frequency;      // Frequency in Hz
  float duty_cycle;     // Duty cycle 0-100%
  bool enabled;         // Output enabled
};

PWMChannel channels[num_channels];

// PWM resolution (bits) - determines duty cycle granularity
// 8-bit = 256 steps (0-255)
const int pwm_resolution = 8;
const int pwm_max_duty = (1 << pwm_resolution) - 1;  // 255 for 8-bit

// Frequency limits
const float min_frequency = 1.0;      // 1 Hz
const float max_frequency = 40000.0;  // 40 kHz

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI PWM Generator");
  Serial.println("==================");

  // Initialize PWM channels
  for (int i = 0; i < num_channels; i++) {
    channels[i].pin = pwm_pins[i];
    channels[i].ledc_channel = i;  // Use LED PWM channels 0-7
    channels[i].frequency = 1000.0;  // Default 1 kHz
    channels[i].duty_cycle = 50.0;   // Default 50% duty cycle
    channels[i].enabled = false;     // Start disabled

    // Configure LED PWM channel
    ledcSetup(channels[i].ledc_channel, channels[i].frequency, pwm_resolution);
    ledcAttachPin(channels[i].pin, channels[i].ledc_channel);

    // Start with output disabled (0% duty cycle)
    ledcWrite(channels[i].ledc_channel, 0);

    Serial.printf("PWM%d: GPIO %d, %.1f Hz, %.1f%%, OFF\n",
                  i + 1, channels[i].pin, channels[i].frequency, channels[i].duty_cycle);
  }

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

// Set PWM frequency for a channel
void set_frequency(int ch, float freq) {
  if (ch < 0 || ch >= num_channels) return;

  // Clamp to valid range
  if (freq < min_frequency) freq = min_frequency;
  if (freq > max_frequency) freq = max_frequency;

  channels[ch].frequency = freq;

  // Reconfigure LED PWM channel with new frequency
  ledcSetup(channels[ch].ledc_channel, channels[ch].frequency, pwm_resolution);

  // Reattach pin (required after ledcSetup)
  ledcAttachPin(channels[ch].pin, channels[ch].ledc_channel);

  // Restore duty cycle if enabled
  if (channels[ch].enabled) {
    apply_duty_cycle(ch);
  }

  Serial.printf("PWM%d frequency -> %.2f Hz\n", ch + 1, freq);
}

// Set PWM duty cycle for a channel
void set_duty_cycle(int ch, float duty) {
  if (ch < 0 || ch >= num_channels) return;

  // Clamp to 0-100%
  if (duty < 0.0) duty = 0.0;
  if (duty > 100.0) duty = 100.0;

  channels[ch].duty_cycle = duty;

  // Apply if enabled
  if (channels[ch].enabled) {
    apply_duty_cycle(ch);
  }

  Serial.printf("PWM%d duty cycle -> %.2f%%\n", ch + 1, duty);
}

// Apply current duty cycle to hardware
void apply_duty_cycle(int ch) {
  if (ch < 0 || ch >= num_channels) return;

  // Convert percentage to PWM value (0-255 for 8-bit)
  int pwm_value = (int)((channels[ch].duty_cycle / 100.0) * pwm_max_duty);

  ledcWrite(channels[ch].ledc_channel, pwm_value);
}

// Enable PWM output
void enable_output(int ch) {
  if (ch < 0 || ch >= num_channels) return;

  channels[ch].enabled = true;
  apply_duty_cycle(ch);

  Serial.printf("PWM%d enabled\n", ch + 1);
}

// Disable PWM output (set to 0% duty cycle)
void disable_output(int ch) {
  if (ch < 0 || ch >= num_channels) return;

  channels[ch].enabled = false;
  ledcWrite(channels[ch].ledc_channel, 0);

  Serial.printf("PWM%d disabled\n", ch + 1);
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
    send_response("N0GQ,ESP32-SCPI-PWM,1.0,2026\n");
  }

  // *RST - Reset (disable all outputs, set to defaults)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < num_channels; i++) {
      disable_output(i);
      channels[i].frequency = 1000.0;
      channels[i].duty_cycle = 50.0;
      ledcSetup(channels[i].ledc_channel, channels[i].frequency, pwm_resolution);
      ledcAttachPin(channels[i].pin, channels[i].ledc_channel);
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error (always none for this simple device)
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // PWM:FREQ (@n),<hz> - Set frequency
  else if (strncmp(cmd, "PWM:FREQ", 8) == 0 && strchr(cmd, ',')) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      float freq = parse_float_value(cmd);
      if (freq > 0) {
        set_frequency(ch, freq);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid frequency\n");
      }
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // PWM:FREQ? (@n) - Query frequency
  else if (strncmp(cmd, "PWM:FREQ?", 9) == 0) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      char response[32];
      snprintf(response, sizeof(response), "%.2f\n", channels[ch].frequency);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // PWM:DUTY (@n),<percent> - Set duty cycle
  else if (strncmp(cmd, "PWM:DUTY", 8) == 0 && strchr(cmd, ',')) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      float duty = parse_float_value(cmd);
      set_duty_cycle(ch, duty);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // PWM:DUTY? (@n) - Query duty cycle
  else if (strncmp(cmd, "PWM:DUTY?", 9) == 0) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      char response[32];
      snprintf(response, sizeof(response), "%.2f\n", channels[ch].duty_cycle);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // PWM:ON (@n) - Enable output
  else if (strncmp(cmd, "PWM:ON", 6) == 0) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      enable_output(ch);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // PWM:OFF (@n) - Disable output
  else if (strncmp(cmd, "PWM:OFF", 7) == 0) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      disable_output(ch);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // PWM:STAT? (@n) - Query enabled state
  else if (strncmp(cmd, "PWM:STAT?", 9) == 0) {
    int ch = parse_channel_number(cmd);
    if (ch >= 0 && ch < num_channels) {
      send_response(channels[ch].enabled ? "1\n" : "0\n");
    } else {
      send_response("ERROR: Invalid channel number\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}

// Parse channel number from SCPI command (e.g., "(@1)" or "(@8)")
// Returns 0-indexed channel number (0-7) or -1 on error
int parse_channel_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int ch = -1;
  sscanf(at_sign, "@%d", &ch);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return ch - 1;
}

// Parse floating point value after comma in SCPI command
// E.g., "PWM:FREQ (@1),1234.5" returns 1234.5
float parse_float_value(const char* cmd) {
  const char* comma = strchr(cmd, ',');
  if (!comma) return 0.0;

  return atof(comma + 1);
}
