/*
 * SCPI Tone Generator for ESP32
 *
 * Generates audio tones via PWM with optional amplitude control
 * Suitable for signal injection, audio testing, and frequency response measurement
 *
 * Hardware connections:
 *   GPIO 25 -> Tone output (PWM carrier, 50% duty cycle)
 *   GPIO 26 -> Amplitude control (optional low-pass filtered PWM for volume)
 *
 *   Connect GPIO 25 to:
 *     - Speaker (8-32 ohm) via series capacitor (100uF) and resistor (100-220 ohm)
 *     - Piezo buzzer (direct connection)
 *     - Audio input via voltage divider if needed (ESP32 is 3.3V logic)
 *
 *   Optional amplitude control (GPIO 26):
 *     - Low-pass filter (1k resistor + 10uF capacitor to ground)
 *     - Output range 0-3.3V proportional to amplitude setting
 *
 * SCPI Commands:
 *   TONE:FREQ,<hz>          Set frequency (20-20000 Hz)
 *   TONE:FREQ?              Query frequency
 *   TONE:AMPL,<0-100>       Set amplitude percent (0-100)
 *   TONE:AMPL?              Query amplitude
 *   TONE:OUTP,<0|1>         Enable/disable output
 *   TONE:OUTP?              Query output state
 *   TONE:BEEP,<freq>,<ms>   Play tone for duration (blocking)
 *   TONE:SWEE,<start>,<end>,<ms>  Frequency sweep (blocking)
 *   *IDN?                   Identification string
 *   *RST                    Reset (440 Hz, 50%, output off)
 *   SYST:ERR?               System error query
 *
 * Serial: 115200 baud, USB CDC
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// GPIO pins
const int TONE_PIN = 25;      // PWM tone output
const int AMPLITUDE_PIN = 26; // PWM amplitude control (0-100% volume)

// LEDC channels
const int TONE_CHANNEL = 0;
const int AMPLITUDE_CHANNEL = 1;

// LEDC PWM parameters for tone generation
const int TONE_RESOLUTION = 10;  // 10-bit resolution (0-1023), 50% duty = 512
const int AMPLITUDE_RESOLUTION = 8; // 8-bit resolution for amplitude (0-255)

// Tone state
float current_frequency = 440.0;  // Hz (A4 note)
int current_amplitude = 50;       // 0-100%
bool output_enabled = false;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Tone Generator");
  Serial.println("===================");

  // Initialize LEDC for tone generation
  // Tone channel: variable frequency, fixed 50% duty cycle
  ledcSetup(TONE_CHANNEL, current_frequency, TONE_RESOLUTION);
  ledcAttachPin(TONE_PIN, TONE_CHANNEL);
  ledcWrite(TONE_CHANNEL, 0);  // Start with tone off

  // Amplitude channel: fixed low frequency (e.g., 5 kHz), variable duty cycle
  // Low-pass filtered to create a DC control voltage proportional to amplitude
  ledcSetup(AMPLITUDE_CHANNEL, 5000, AMPLITUDE_RESOLUTION);  // 5 kHz carrier
  ledcAttachPin(AMPLITUDE_PIN, AMPLITUDE_CHANNEL);
  set_amplitude_pwm(current_amplitude);

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
  Serial.println("Default: 440 Hz, 50% amplitude, output OFF");

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

      // Handle command termination
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

// Set frequency and update tone output
void set_frequency(float freq) {
  if (freq < 20.0) freq = 20.0;
  if (freq > 20000.0) freq = 20000.0;

  current_frequency = freq;
  ledcWriteTone(TONE_CHANNEL, current_frequency);

  // If output is disabled, ensure PWM duty cycle is 0
  if (!output_enabled) {
    ledcWrite(TONE_CHANNEL, 0);
  } else {
    // Set 50% duty cycle for tone output
    int duty = (1 << TONE_RESOLUTION) / 2;  // 50% of max resolution
    ledcWrite(TONE_CHANNEL, duty);
  }
}

// Set amplitude PWM (0-100% maps to 0-255 duty cycle on amplitude channel)
void set_amplitude_pwm(int amplitude) {
  if (amplitude < 0) amplitude = 0;
  if (amplitude > 100) amplitude = 100;

  current_amplitude = amplitude;

  // Map 0-100% to 0-255 (8-bit PWM duty cycle)
  int duty = map(amplitude, 0, 100, 0, 255);
  ledcWrite(AMPLITUDE_CHANNEL, duty);
}

// Enable/disable tone output
void set_output(bool enabled) {
  output_enabled = enabled;

  if (enabled) {
    // Enable tone: set 50% duty cycle at current frequency
    int duty = (1 << TONE_RESOLUTION) / 2;
    ledcWriteTone(TONE_CHANNEL, current_frequency);
    ledcWrite(TONE_CHANNEL, duty);
  } else {
    // Disable tone: set duty cycle to 0 (pin LOW)
    ledcWrite(TONE_CHANNEL, 0);
  }
}

// Play a beep (blocking)
void beep(float freq, unsigned long duration_ms) {
  float saved_freq = current_frequency;
  bool saved_output = output_enabled;

  set_frequency(freq);
  set_output(true);
  delay(duration_ms);
  set_output(saved_output);
  set_frequency(saved_freq);
}

// Frequency sweep (blocking)
void sweep(float start_freq, float end_freq, unsigned long duration_ms) {
  bool saved_output = output_enabled;
  set_output(true);

  unsigned long start_time = millis();
  unsigned long elapsed;

  while ((elapsed = millis() - start_time) < duration_ms) {
    float progress = (float)elapsed / (float)duration_ms;
    float freq = start_freq + (end_freq - start_freq) * progress;
    set_frequency(freq);
    delay(10);  // 100 Hz update rate
  }

  set_output(saved_output);
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
    send_response("N0GQ,ESP32-SCPI-Tone,1.0,2026\n");
  }

  // *RST - Reset to defaults
  else if (strcmp(cmd, "*RST") == 0) {
    set_frequency(440.0);
    set_amplitude_pwm(50);
    set_output(false);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // TONE:FREQ,<hz> - Set frequency
  else if (strncmp(cmd, "TONE:FREQ,", 10) == 0) {
    float freq = atof(cmd + 10);
    if (freq >= 20.0 && freq <= 20000.0) {
      set_frequency(freq);
      send_response("OK\n");
    } else {
      send_response("ERROR: Frequency out of range (20-20000 Hz)\n");
    }
  }

  // TONE:FREQ? - Query frequency
  else if (strcmp(cmd, "TONE:FREQ?") == 0) {
    char response[32];
    snprintf(response, sizeof(response), "%.2f\n", current_frequency);
    send_response(response);
  }

  // TONE:AMPL,<0-100> - Set amplitude
  else if (strncmp(cmd, "TONE:AMPL,", 10) == 0) {
    int amplitude = atoi(cmd + 10);
    if (amplitude >= 0 && amplitude <= 100) {
      set_amplitude_pwm(amplitude);
      send_response("OK\n");
    } else {
      send_response("ERROR: Amplitude out of range (0-100%)\n");
    }
  }

  // TONE:AMPL? - Query amplitude
  else if (strcmp(cmd, "TONE:AMPL?") == 0) {
    char response[16];
    snprintf(response, sizeof(response), "%d\n", current_amplitude);
    send_response(response);
  }

  // TONE:OUTP,<0|1> - Set output state
  else if (strncmp(cmd, "TONE:OUTP,", 10) == 0) {
    int state = atoi(cmd + 10);
    set_output(state != 0);
    send_response("OK\n");
  }

  // TONE:OUTP? - Query output state
  else if (strcmp(cmd, "TONE:OUTP?") == 0) {
    send_response(output_enabled ? "1\n" : "0\n");
  }

  // TONE:BEEP,<freq>,<ms> - Play beep
  else if (strncmp(cmd, "TONE:BEEP,", 10) == 0) {
    float freq;
    int duration_ms;
    if (sscanf(cmd + 10, "%f,%d", &freq, &duration_ms) == 2) {
      if (freq >= 20.0 && freq <= 20000.0 && duration_ms > 0 && duration_ms <= 60000) {
        beep(freq, duration_ms);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid parameters (freq: 20-20000 Hz, duration: 1-60000 ms)\n");
      }
    } else {
      send_response("ERROR: Invalid BEEP syntax (expected TONE:BEEP,<freq>,<ms>)\n");
    }
  }

  // TONE:SWEE,<start>,<end>,<ms> - Frequency sweep
  else if (strncmp(cmd, "TONE:SWEE,", 10) == 0) {
    float start_freq, end_freq;
    int duration_ms;
    if (sscanf(cmd + 10, "%f,%f,%d", &start_freq, &end_freq, &duration_ms) == 3) {
      if (start_freq >= 20.0 && start_freq <= 20000.0 &&
          end_freq >= 20.0 && end_freq <= 20000.0 &&
          duration_ms > 0 && duration_ms <= 60000) {
        sweep(start_freq, end_freq, duration_ms);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid parameters (freq: 20-20000 Hz, duration: 1-60000 ms)\n");
      }
    } else {
      send_response("ERROR: Invalid SWEEP syntax (expected TONE:SWEE,<start>,<end>,<ms>)\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
