/*
 * SCPI Servo Controller for ESP32
 *
 * Controls 4 RC servos via SCPI commands over TCP/IP
 * Compatible with standard hobby servos (SG90, MG996R, etc.)
 *
 * Hardware connections:
 *   Servo 1 -> GPIO 25 (PWM)
 *   Servo 2 -> GPIO 26 (PWM)
 *   Servo 3 -> GPIO 27 (PWM)
 *   Servo 4 -> GPIO 14 (PWM)
 *
 *   All servos:
 *     Signal -> GPIO (listed above)
 *     VCC    -> External 5V power supply (NOT from ESP32!)
 *     GND    -> Common ground with ESP32
 *
 * CRITICAL: Servos draw significant current (>500mA under load).
 * Power them from an external 5V supply, NOT from the ESP32's 5V pin.
 * Connect grounds together (ESP32 GND + servo power GND).
 *
 * Standard RC servo timing:
 *   1000 µs pulse -> 0° position
 *   1500 µs pulse -> 90° position (center)
 *   2000 µs pulse -> 180° position
 *   Pulse repeated at 50 Hz (20 ms period)
 */

#include <WiFi.h>
#include <ESP32Servo.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Servo objects and GPIO pins
Servo servos[4];
const int servo_pins[4] = {25, 26, 27, 14};
const int num_servos = 4;

// Servo positions (degrees, 0-180)
int servo_positions[4] = {90, 90, 90, 90};  // Start at center

// Servo pulse width limits (microseconds)
// Standard: 1000-2000 µs, but can be adjusted for non-standard servos
const int servo_min_us = 1000;  // Min pulse width (0°)
const int servo_max_us = 2000;  // Max pulse width (180°)

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Servo Controller");
  Serial.println("=====================");

  // Initialize servos
  for (int i = 0; i < num_servos; i++) {
    servos[i].setPeriodHertz(50);  // Standard RC servo frequency (50 Hz)
    servos[i].attach(servo_pins[i], servo_min_us, servo_max_us);
    servos[i].write(servo_positions[i]);  // Move to center position
    Serial.printf("Servo %d: GPIO %d, position %d°\n", i+1, servo_pins[i], servo_positions[i]);
  }

  Serial.println("\nWARNING: Servos must be powered from external 5V supply!");
  Serial.println("         Do NOT power servos from ESP32 5V pin!\n");

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
}

// Set servo position (0-180 degrees)
void set_servo_position(int servo, int angle) {
  if (servo < 0 || servo >= num_servos) return;

  // Clamp angle to valid range
  if (angle < 0) angle = 0;
  if (angle > 180) angle = 180;

  servo_positions[servo] = angle;
  servos[servo].write(angle);

  Serial.printf("Servo %d -> %d°\n", servo + 1, angle);
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Parse servo number from SCPI command (e.g., "(@1)" or "(@4)")
int parse_servo_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int servo = -1;
  sscanf(at_sign, "@%d", &servo);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return servo - 1;
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
    send_response("N0GQ,ESP32-SCPI-Servo,1.0,2026\n");
  }

  // *RST - Reset (all servos to center: 90°)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < num_servos; i++) {
      set_servo_position(i, 90);
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // SERV:POS (@n),<angle> - Set servo n to angle (0-180)
  else if (strncmp(cmd, "SERV:POS", 8) == 0 || strncmp(cmd, "SERVO:POSITION", 14) == 0) {
    int servo = parse_servo_number(cmd);

    // Find the comma after (@n)
    const char* comma = strchr(cmd, ',');

    if (servo >= 0 && servo < num_servos && comma) {
      int angle;
      if (sscanf(comma + 1, "%d", &angle) == 1) {
        set_servo_position(servo, angle);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid angle\n");
      }
    } else {
      send_response("ERROR: Invalid servo number or syntax\n");
    }
  }

  // SERV:POS? (@n) - Query servo n position
  else if (strncmp(cmd, "SERV:POS?", 9) == 0 || strncmp(cmd, "SERVO:POSITION?", 15) == 0) {
    int servo = parse_servo_number(cmd);

    if (servo >= 0 && servo < num_servos) {
      snprintf(response, sizeof(response), "%d\n", servo_positions[servo]);
      send_response(response);
    } else {
      send_response("ERROR: Invalid servo number\n");
    }
  }

  // SERV:CENT (@n) - Center servo n (90°)
  else if (strncmp(cmd, "SERV:CENT", 9) == 0 || strncmp(cmd, "SERVO:CENTER", 12) == 0) {
    int servo = parse_servo_number(cmd);

    if (servo >= 0 && servo < num_servos) {
      set_servo_position(servo, 90);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid servo number\n");
    }
  }

  // SERV:MIN (@n) - Move servo n to minimum (0°)
  else if (strncmp(cmd, "SERV:MIN", 8) == 0 || strncmp(cmd, "SERVO:MINIMUM", 13) == 0) {
    int servo = parse_servo_number(cmd);

    if (servo >= 0 && servo < num_servos) {
      set_servo_position(servo, 0);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid servo number\n");
    }
  }

  // SERV:MAX (@n) - Move servo n to maximum (180°)
  else if (strncmp(cmd, "SERV:MAX", 8) == 0 || strncmp(cmd, "SERVO:MAXIMUM", 13) == 0) {
    int servo = parse_servo_number(cmd);

    if (servo >= 0 && servo < num_servos) {
      set_servo_position(servo, 180);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid servo number\n");
    }
  }

  // SERV:ALL,<angle> - Set all servos to angle
  else if (strncmp(cmd, "SERV:ALL", 8) == 0 || strncmp(cmd, "SERVO:ALL", 9) == 0) {
    // Find the comma
    const char* comma = strchr(cmd, ',');

    if (comma) {
      int angle;
      if (sscanf(comma + 1, "%d", &angle) == 1) {
        for (int i = 0; i < num_servos; i++) {
          set_servo_position(i, angle);
        }
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid angle\n");
      }
    } else {
      send_response("ERROR: Missing angle parameter\n");
    }
  }

  // SERV:ALL:CENT - Center all servos (90°)
  else if (strcmp(cmd, "SERV:ALL:CENT") == 0 || strcmp(cmd, "SERVO:ALL:CENTER") == 0) {
    for (int i = 0; i < num_servos; i++) {
      set_servo_position(i, 90);
    }
    send_response("OK\n");
  }

  // SERV:SWEEP (@n),<start>,<end>,<step>,<delay_ms> - Sweep servo from start to end
  else if (strncmp(cmd, "SERV:SWEEP", 10) == 0 || strncmp(cmd, "SERVO:SWEEP", 11) == 0) {
    int servo = parse_servo_number(cmd);

    if (servo >= 0 && servo < num_servos) {
      // Parse sweep parameters
      const char* comma1 = strchr(cmd, ',');
      if (!comma1) {
        send_response("ERROR: Missing sweep parameters\n");
        return;
      }

      int start_angle, end_angle, step, delay_ms;
      if (sscanf(comma1 + 1, "%d,%d,%d,%d", &start_angle, &end_angle, &step, &delay_ms) == 4) {
        // Validate parameters
        if (step <= 0) step = 1;
        if (delay_ms < 0) delay_ms = 0;

        // Perform sweep
        if (start_angle < end_angle) {
          // Sweep up
          for (int angle = start_angle; angle <= end_angle; angle += step) {
            set_servo_position(servo, angle);
            delay(delay_ms);
          }
        } else {
          // Sweep down
          for (int angle = start_angle; angle >= end_angle; angle -= step) {
            set_servo_position(servo, angle);
            delay(delay_ms);
          }
        }

        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid sweep parameters (need start,end,step,delay)\n");
      }
    } else {
      send_response("ERROR: Invalid servo number\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
