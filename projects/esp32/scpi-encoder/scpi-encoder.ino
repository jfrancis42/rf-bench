/*
 * SCPI Rotary Encoder Controller for ESP32
 *
 * Dual rotary encoder interface with interrupt-driven quadrature decoding
 * Tracks position, rate, and direction for automation and remote control
 *
 * Hardware connections:
 *   Encoder 1:
 *     GPIO 25 -> Phase A (CLK)
 *     GPIO 26 -> Phase B (DT)
 *
 *   Encoder 2:
 *     GPIO 27 -> Phase A (CLK)
 *     GPIO 14 -> Phase B (DT)
 *
 * Encoder type: Incremental rotary encoder with quadrature outputs
 * Common models: KY-040, EC11, PEC11, or any quadrature encoder
 * Pull-ups: Most encoder modules have built-in pull-ups; internal pull-ups enabled as backup
 *
 * SCPI commands over TCP port 5025:
 *   ENC:POS? (@n)         - Read position in counts
 *   ENC:POS (@n),<value>  - Set position (re-zero or preset)
 *   ENC:RATE? (@n)        - Counts per second (signed)
 *   ENC:DIR? (@n)         - Direction (CW=1, CCW=-1, STOP=0)
 *   ENC:RES (@n)          - Reset position to zero
 *
 * Channel numbering: @1 or @2 (SCPI convention, 1-indexed)
 *
 * Quadrature decoding: Gray-code state machine in ISR, 4× resolution (counts every edge)
 * Rate calculation: Moving average over 500ms window
 * Thread-safe: Atomic operations and volatile variables for ISR↔main communication
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Number of encoders
const int num_encoders = 2;

// Encoder GPIO pins (A = CLK, B = DT)
const int encoder_pins_a[num_encoders] = {25, 27};
const int encoder_pins_b[num_encoders] = {26, 14};

// Encoder state (volatile for ISR access)
struct EncoderState {
  volatile long position;          // Accumulated position in counts
  volatile long last_position;     // Position at last rate calculation
  volatile unsigned long last_time; // Timestamp of last edge (micros)
  volatile unsigned long rate_window_start; // Start of rate measurement window
  volatile int direction;          // Last direction: 1=CW, -1=CCW, 0=stopped
  volatile byte state;             // Current quadrature state (2-bit Gray code)
  volatile bool moving;            // True if encoder moved in last 100ms
};

EncoderState encoders[num_encoders];

// Rate calculation window (microseconds)
const unsigned long rate_window_us = 500000; // 500ms

// Direction/stop timeout (if no motion for this long, direction = 0)
const unsigned long stop_timeout_us = 100000; // 100ms

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// Quadrature state table for 4× resolution decoding
// [old_state][new_state] = delta (-1, 0, +1)
// State encoding: (B<<1) | A
const int8_t quadrature_table[4][4] = {
  { 0, -1,  1,  0},  // 00 -> 00,01,10,11
  { 1,  0,  0, -1},  // 01 -> 00,01,10,11
  {-1,  0,  0,  1},  // 10 -> 00,01,10,11
  { 0,  1, -1,  0}   // 11 -> 00,01,10,11
};

// ISR for encoder 1
void IRAM_ATTR encoder1_isr() {
  encoder_isr(0);
}

// ISR for encoder 2
void IRAM_ATTR encoder2_isr() {
  encoder_isr(1);
}

// Generic encoder ISR (called by both encoder ISRs)
void IRAM_ATTR encoder_isr(int enc_num) {
  if (enc_num < 0 || enc_num >= num_encoders) return;

  EncoderState* enc = &encoders[enc_num];

  // Read current state of both pins
  byte a = digitalRead(encoder_pins_a[enc_num]);
  byte b = digitalRead(encoder_pins_b[enc_num]);
  byte new_state = (b << 1) | a;

  // Lookup transition delta from state table
  int8_t delta = quadrature_table[enc->state][new_state];

  // Update position
  enc->position += delta;

  // Update direction if delta is non-zero
  if (delta != 0) {
    enc->direction = (delta > 0) ? 1 : -1;
    enc->last_time = micros();
    enc->moving = true;
  }

  // Update state
  enc->state = new_state;
}

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Rotary Encoder Controller");
  Serial.println("===============================");

  // Initialize encoder structures
  for (int i = 0; i < num_encoders; i++) {
    encoders[i].position = 0;
    encoders[i].last_position = 0;
    encoders[i].last_time = micros();
    encoders[i].rate_window_start = micros();
    encoders[i].direction = 0;
    encoders[i].moving = false;

    // Configure GPIO with internal pull-ups (most encoder modules have external pull-ups too)
    pinMode(encoder_pins_a[i], INPUT_PULLUP);
    pinMode(encoder_pins_b[i], INPUT_PULLUP);

    // Read initial state
    byte a = digitalRead(encoder_pins_a[i]);
    byte b = digitalRead(encoder_pins_b[i]);
    encoders[i].state = (b << 1) | a;
  }

  // Attach interrupts to both A and B pins for 4× resolution
  // CHANGE triggers on both rising and falling edges
  attachInterrupt(digitalPinToInterrupt(encoder_pins_a[0]), encoder1_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(encoder_pins_b[0]), encoder1_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(encoder_pins_a[1]), encoder2_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(encoder_pins_b[1]), encoder2_isr, CHANGE);

  Serial.println("Encoders initialized:");
  Serial.printf("  Encoder 1: A=GPIO%d, B=GPIO%d\n", encoder_pins_a[0], encoder_pins_b[0]);
  Serial.printf("  Encoder 2: A=GPIO%d, B=GPIO%d\n", encoder_pins_a[1], encoder_pins_b[1]);

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

  // Update encoder rate and direction (every loop iteration)
  update_encoder_states();
}

// Update rate calculation and direction/stop detection
void update_encoder_states() {
  unsigned long now = micros();

  for (int i = 0; i < num_encoders; i++) {
    EncoderState* enc = &encoders[i];

    // Check if encoder has stopped (no edge in last 100ms)
    if (enc->moving && (now - enc->last_time > stop_timeout_us)) {
      enc->moving = false;
      enc->direction = 0;
    }
  }
}

// Calculate encoder rate in counts per second
float get_encoder_rate(int enc_num) {
  if (enc_num < 0 || enc_num >= num_encoders) return 0.0;

  EncoderState* enc = &encoders[enc_num];
  unsigned long now = micros();

  // Calculate time delta
  unsigned long dt = now - enc->rate_window_start;
  if (dt == 0) return 0.0;

  // Calculate position delta (thread-safe read via temporary)
  long current_pos = enc->position;
  long delta_pos = current_pos - enc->last_position;

  // Reset rate window every 500ms
  if (dt >= rate_window_us) {
    enc->last_position = current_pos;
    enc->rate_window_start = now;
  }

  // Convert to counts per second
  float rate = (float)delta_pos / (float)dt * 1e6;

  return rate;
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
    send_response("N0GQ,ESP32-SCPI-Encoder,1.0,2026\n");
  }

  // *RST - Reset (zero all encoders)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < num_encoders; i++) {
      encoders[i].position = 0;
      encoders[i].last_position = 0;
      encoders[i].rate_window_start = micros();
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error (always none for this simple device)
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // ENC:POS? (@n) - Read encoder position
  else if (strncmp(cmd, "ENC:POS?", 8) == 0 || strncmp(cmd, "ENCODER:POSITION?", 17) == 0) {
    int enc_num = parse_encoder_number(cmd);
    if (enc_num >= 0 && enc_num < num_encoders) {
      char response[32];
      snprintf(response, sizeof(response), "%ld\n", encoders[enc_num].position);
      send_response(response);
    } else {
      send_response("ERROR: Invalid encoder number\n");
    }
  }

  // ENC:POS (@n),<value> - Set encoder position
  else if (strncmp(cmd, "ENC:POS", 7) == 0 || strncmp(cmd, "ENCODER:POSITION", 16) == 0) {
    int enc_num = parse_encoder_number(cmd);
    if (enc_num >= 0 && enc_num < num_encoders) {
      // Find comma after (@n)
      const char* comma = strchr(cmd, ',');
      if (comma) {
        long value = atol(comma + 1);
        encoders[enc_num].position = value;
        encoders[enc_num].last_position = value;
        send_response("OK\n");
      } else {
        send_response("ERROR: Missing value\n");
      }
    } else {
      send_response("ERROR: Invalid encoder number\n");
    }
  }

  // ENC:RATE? (@n) - Read encoder rate (counts per second)
  else if (strncmp(cmd, "ENC:RATE?", 9) == 0 || strncmp(cmd, "ENCODER:RATE?", 13) == 0) {
    int enc_num = parse_encoder_number(cmd);
    if (enc_num >= 0 && enc_num < num_encoders) {
      float rate = get_encoder_rate(enc_num);
      char response[32];
      snprintf(response, sizeof(response), "%.2f\n", rate);
      send_response(response);
    } else {
      send_response("ERROR: Invalid encoder number\n");
    }
  }

  // ENC:DIR? (@n) - Read encoder direction
  else if (strncmp(cmd, "ENC:DIR?", 8) == 0 || strncmp(cmd, "ENCODER:DIRECTION?", 18) == 0) {
    int enc_num = parse_encoder_number(cmd);
    if (enc_num >= 0 && enc_num < num_encoders) {
      char response[8];
      snprintf(response, sizeof(response), "%d\n", encoders[enc_num].direction);
      send_response(response);
    } else {
      send_response("ERROR: Invalid encoder number\n");
    }
  }

  // ENC:RES (@n) - Reset encoder to zero
  else if (strncmp(cmd, "ENC:RES", 7) == 0 || strncmp(cmd, "ENCODER:RESET", 13) == 0) {
    int enc_num = parse_encoder_number(cmd);
    if (enc_num >= 0 && enc_num < num_encoders) {
      encoders[enc_num].position = 0;
      encoders[enc_num].last_position = 0;
      encoders[enc_num].rate_window_start = micros();
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid encoder number\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}

// Parse encoder number from SCPI command (e.g., "(@1)" or "(@2)")
int parse_encoder_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int enc_num = -1;
  sscanf(at_sign, "@%d", &enc_num);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return enc_num - 1;
}
