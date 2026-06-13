/*
 * SCPI Stepper Motor Controller for ESP32
 *
 * Controls 2 stepper motors via A4988 or DRV8825 drivers over SCPI commands via TCP/IP
 * Compatible with standard bipolar stepper motors (NEMA 17, NEMA 23, etc.)
 *
 * Hardware connections:
 *   Motor 1:
 *     STEP -> GPIO 25
 *     DIR  -> GPIO 26
 *     EN   -> GPIO 27 (active-low: LOW = enabled)
 *
 *   Motor 2:
 *     STEP -> GPIO 14
 *     DIR  -> GPIO 32
 *     EN   -> GPIO 33 (active-low: LOW = enabled)
 *
 *   Driver power:
 *     VMOT -> External 12V power supply (8-35V depending on driver/motor)
 *     GND  -> Common ground with ESP32
 *
 * CRITICAL: Motors are powered from external supply, NOT from ESP32.
 * Stepper drivers can draw several amps. Share GND with ESP32 for signal reference.
 *
 * A4988 vs DRV8825:
 *   A4988:  Max 2A/phase, up to 35V, microstepping via MS1/MS2/MS3 pins
 *   DRV8825: Max 2.5A/phase, up to 45V, microstepping via M0/M1/M2 pins
 *   Both use identical STEP/DIR/EN interface (hardware-compatible)
 *
 * Microstepping modes (configured via driver hardware pins, not via SCPI):
 *   Full step    (200 steps/rev for 1.8° motor)
 *   Half step    (400 steps/rev)
 *   1/4 step     (800 steps/rev)
 *   1/8 step     (1600 steps/rev)
 *   1/16 step    (3200 steps/rev) [A4988]
 *   1/32 step    (6400 steps/rev) [DRV8825 only]
 *
 * Position tracking: Relative step count (no absolute position without endstops/encoders)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Motor GPIO pins [motor_index]
const int step_pins[2] = {25, 14};
const int dir_pins[2] = {26, 32};
const int en_pins[2] = {27, 33};
const int num_motors = 2;

// Motor states
struct MotorState {
  long position;              // Current position in steps (signed, can be negative)
  unsigned long step_delay_us; // Microseconds between steps (determines speed)
  bool enabled;               // Motor enabled state
  bool direction_cw;          // true = CW, false = CCW
  unsigned long last_step_us; // micros() of last step (for non-blocking motion)
  long target_position;       // Target position for move commands
  bool moving;                // true if motor is currently moving
};

MotorState motors[2];

// Driver timing constants
const unsigned long MIN_STEP_PULSE_US = 2;   // Minimum HIGH pulse width (A4988: 1µs, DRV8825: 1.9µs)
const unsigned long MIN_STEP_DELAY_US = 100; // Minimum delay between steps (max speed ~10 kHz)

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Stepper Motor Controller");
  Serial.println("==============================");

  // Initialize motor pins
  for (int i = 0; i < num_motors; i++) {
    pinMode(step_pins[i], OUTPUT);
    pinMode(dir_pins[i], OUTPUT);
    pinMode(en_pins[i], OUTPUT);

    // Initialize motor state
    motors[i].position = 0;
    motors[i].step_delay_us = 1000; // Default: 1ms between steps = 1000 steps/sec
    motors[i].enabled = false;
    motors[i].direction_cw = true;
    motors[i].last_step_us = 0;
    motors[i].target_position = 0;
    motors[i].moving = false;

    // Set initial pin states
    digitalWrite(step_pins[i], LOW);
    digitalWrite(dir_pins[i], LOW); // LOW = CW (driver-dependent)
    digitalWrite(en_pins[i], HIGH); // HIGH = disabled (active-low enable)

    Serial.printf("Motor %d: STEP=%d, DIR=%d, EN=%d (disabled)\n",
                  i+1, step_pins[i], dir_pins[i], en_pins[i]);
  }

  Serial.println("\nWARNING: Motors must be powered from external 12V supply!");
  Serial.println("         Connect ESP32 GND to motor supply GND!\n");

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
  // Update motor positions (non-blocking motion)
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

// Update motor positions (called every loop iteration for non-blocking motion)
void update_motors() {
  unsigned long now = micros();

  for (int i = 0; i < num_motors; i++) {
    if (!motors[i].moving || !motors[i].enabled) continue;

    // Check if it's time for the next step
    if (now - motors[i].last_step_us >= motors[i].step_delay_us) {
      // Determine direction
      bool step_forward = motors[i].target_position > motors[i].position;

      // Check if we've reached target
      if (motors[i].position == motors[i].target_position) {
        motors[i].moving = false;
        continue;
      }

      // Set direction pin
      digitalWrite(dir_pins[i], step_forward ? HIGH : LOW);
      delayMicroseconds(1); // Direction setup time

      // Generate step pulse
      digitalWrite(step_pins[i], HIGH);
      delayMicroseconds(MIN_STEP_PULSE_US);
      digitalWrite(step_pins[i], LOW);

      // Update position
      motors[i].position += step_forward ? 1 : -1;
      motors[i].last_step_us = now;
    }
  }
}

// Move motor by relative steps (positive = forward, negative = backward)
void move_motor_steps(int motor, long steps) {
  if (motor < 0 || motor >= num_motors) return;
  if (!motors[motor].enabled) {
    send_response("ERROR: Motor disabled\n");
    return;
  }

  // Set target position
  motors[motor].target_position = motors[motor].position + steps;
  motors[motor].moving = true;

  Serial.printf("Motor %d: moving %ld steps (pos %ld -> %ld)\n",
                motor + 1, steps, motors[motor].position, motors[motor].target_position);

  send_response("OK\n");
}

// Set motor speed in RPM (revolutions per minute)
// Assumes 200 steps/revolution (1.8° motor at full step)
// Speed calculation: steps/sec = (RPM * steps_per_rev) / 60
//                    delay_us = 1,000,000 / steps_per_sec
void set_motor_speed_rpm(int motor, float rpm) {
  if (motor < 0 || motor >= num_motors) return;

  // Assume 200 steps/rev (full step); adjust if using microstepping
  const int steps_per_rev = 200;

  float steps_per_sec = (rpm * steps_per_rev) / 60.0;

  if (steps_per_sec < 1.0) steps_per_sec = 1.0; // Minimum speed

  unsigned long delay_us = (unsigned long)(1000000.0 / steps_per_sec);

  if (delay_us < MIN_STEP_DELAY_US) delay_us = MIN_STEP_DELAY_US;

  motors[motor].step_delay_us = delay_us;

  Serial.printf("Motor %d: speed %.2f RPM (delay %lu µs)\n",
                motor + 1, rpm, delay_us);
}

// Enable or disable motor
void set_motor_enable(int motor, bool enable) {
  if (motor < 0 || motor >= num_motors) return;

  motors[motor].enabled = enable;
  digitalWrite(en_pins[motor], enable ? LOW : HIGH); // Active-low enable

  Serial.printf("Motor %d: %s\n", motor + 1, enable ? "enabled" : "disabled");
}

// Emergency stop motor
void stop_motor(int motor) {
  if (motor < 0 || motor >= num_motors) return;

  motors[motor].moving = false;
  motors[motor].target_position = motors[motor].position;

  Serial.printf("Motor %d: emergency stop at position %ld\n",
                motor + 1, motors[motor].position);
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Parse motor number from SCPI command (e.g., "(@1)" or "(@2)")
int parse_motor_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int motor = -1;
  sscanf(at_sign, "@%d", &motor);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return motor - 1;
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
    send_response("N0GQ,ESP32-SCPI-Stepper,1.0,2026\n");
  }

  // *RST - Reset (stop all motors, home all positions to 0)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < num_motors; i++) {
      stop_motor(i);
      motors[i].position = 0;
      motors[i].target_position = 0;
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // STEP:POS (@n),<steps> - Move motor n by relative steps
  else if (strncmp(cmd, "STEP:POS", 8) == 0) {
    int motor = parse_motor_number(cmd);
    const char* comma = strchr(cmd, ',');

    if (motor >= 0 && motor < num_motors && comma) {
      long steps;
      if (sscanf(comma + 1, "%ld", &steps) == 1) {
        move_motor_steps(motor, steps);
      } else {
        send_response("ERROR: Invalid step count\n");
      }
    } else {
      send_response("ERROR: Invalid motor number or syntax\n");
    }
  }

  // STEP:POS? (@n) - Query motor n position
  else if (strncmp(cmd, "STEP:POS?", 9) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      snprintf(response, sizeof(response), "%ld\n", motors[motor].position);
      send_response(response);
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:HOME (@n) - Reset position counter to zero
  else if (strncmp(cmd, "STEP:HOME", 9) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      stop_motor(motor);
      motors[motor].position = 0;
      motors[motor].target_position = 0;
      send_response("OK\n");
      Serial.printf("Motor %d: position reset to 0\n", motor + 1);
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:SPEED (@n),<rpm> - Set motor n speed in RPM
  else if (strncmp(cmd, "STEP:SPEED", 10) == 0 && !strstr(cmd, "?")) {
    int motor = parse_motor_number(cmd);
    const char* comma = strchr(cmd, ',');

    if (motor >= 0 && motor < num_motors && comma) {
      float rpm;
      if (sscanf(comma + 1, "%f", &rpm) == 1) {
        if (rpm > 0) {
          set_motor_speed_rpm(motor, rpm);
          send_response("OK\n");
        } else {
          send_response("ERROR: Speed must be positive\n");
        }
      } else {
        send_response("ERROR: Invalid speed value\n");
      }
    } else {
      send_response("ERROR: Invalid motor number or syntax\n");
    }
  }

  // STEP:SPEED? (@n) - Query motor n speed
  else if (strncmp(cmd, "STEP:SPEED?", 11) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      // Convert delay back to RPM (assumes 200 steps/rev)
      const int steps_per_rev = 200;
      float steps_per_sec = 1000000.0 / motors[motor].step_delay_us;
      float rpm = (steps_per_sec * 60.0) / steps_per_rev;

      snprintf(response, sizeof(response), "%.2f\n", rpm);
      send_response(response);
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:EN (@n),<0|1> - Enable/disable motor n
  else if (strncmp(cmd, "STEP:EN", 7) == 0 && !strstr(cmd, "?")) {
    int motor = parse_motor_number(cmd);
    const char* comma = strchr(cmd, ',');

    if (motor >= 0 && motor < num_motors && comma) {
      int enable;
      if (sscanf(comma + 1, "%d", &enable) == 1) {
        set_motor_enable(motor, enable != 0);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid enable value (use 0 or 1)\n");
      }
    } else {
      send_response("ERROR: Invalid motor number or syntax\n");
    }
  }

  // STEP:EN? (@n) - Query motor n enable state
  else if (strncmp(cmd, "STEP:EN?", 8) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      send_response(motors[motor].enabled ? "1\n" : "0\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:DIR (@n),<CW|CCW> - Set motor direction (informational only, actual direction determined by move sign)
  else if (strncmp(cmd, "STEP:DIR", 8) == 0 && !strstr(cmd, "?")) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      // Direction is determined by the sign of the move command, not stored state
      // This command exists for API compatibility but doesn't affect behavior
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:DIR? (@n) - Query motor direction
  else if (strncmp(cmd, "STEP:DIR?", 9) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      // Report current direction based on target vs position
      bool moving_forward = motors[motor].target_position > motors[motor].position;
      send_response(moving_forward ? "CW\n" : "CCW\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:STOP (@n) - Emergency stop motor n
  else if (strncmp(cmd, "STEP:STOP", 9) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      stop_motor(motor);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // STEP:STAT? (@n) - Query motor n status (moving or stopped)
  else if (strncmp(cmd, "STEP:STAT?", 10) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      send_response(motors[motor].moving ? "MOVING\n" : "STOPPED\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
