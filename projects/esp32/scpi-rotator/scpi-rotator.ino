/*
 * SCPI Antenna Rotator Controller for ESP32
 *
 * Controls 2 RC servos (azimuth and elevation) with 4 limit switches for safe antenna positioning.
 * Compatible with standard hobby servos (SG90, MG996R, etc.).
 *
 * Hardware connections:
 *   Azimuth Servo  -> GPIO 25 (PWM)
 *   Elevation Servo -> GPIO 26 (PWM)
 *
 *   Limit switches (normally open, pulled low):
 *   Az CW limit   -> GPIO 32 (input, pull-down)
 *   Az CCW limit  -> GPIO 33 (input, pull-down)
 *   El Up limit   -> GPIO 35 (input, pull-down)
 *   El Down limit -> GPIO 34 (input, pull-down)
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
 * Limit switches prevent mechanical damage by blocking motion when activated.
 * They should be normally open and close when the antenna reaches physical limits.
 *
 * Calibration constants map servo angles (0-180°) to antenna angles:
 *   Azimuth: 0-360° (0° = North, 90° = East, 180° = South, 270° = West)
 *   Elevation: 0-90° (0° = Horizon, 90° = Zenith)
 *
 * Standard RC servo timing:
 *   1000 µs pulse -> 0° servo position
 *   1500 µs pulse -> 90° servo position (center)
 *   2000 µs pulse -> 180° servo position
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
Servo az_servo;
Servo el_servo;
const int az_servo_pin = 25;
const int el_servo_pin = 26;

// Limit switch GPIO pins (normally open, pulled low)
const int az_cw_limit_pin = 32;
const int az_ccw_limit_pin = 33;
const int el_up_limit_pin = 35;
const int el_down_limit_pin = 34;

// Current antenna positions (degrees)
float az_angle = 0.0;    // Azimuth: 0-360° (0 = North)
float el_angle = 0.0;    // Elevation: 0-90° (0 = Horizon, 90 = Zenith)

// Servo to antenna angle calibration
// These constants map servo angles (0-180°) to antenna angles
// Adjust based on your mechanical installation
const float az_servo_min = 0.0;      // Servo angle for 0° azimuth
const float az_servo_max = 180.0;    // Servo angle for 360° azimuth
const float el_servo_min = 0.0;      // Servo angle for 0° elevation
const float el_servo_max = 180.0;    // Servo angle for 90° elevation

// Slew speed (degrees per second) for smooth motion
float slew_speed = 30.0;  // Default: 30°/sec

// Servo pulse width limits (microseconds)
const int servo_min_us = 1000;  // Min pulse width (0°)
const int servo_max_us = 2000;  // Max pulse width (180°)

// Emergency stop flag
bool emergency_stop = false;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Antenna Rotator Controller");
  Serial.println("================================");

  // Initialize limit switch inputs with pull-down resistors
  pinMode(az_cw_limit_pin, INPUT_PULLDOWN);
  pinMode(az_ccw_limit_pin, INPUT_PULLDOWN);
  pinMode(el_up_limit_pin, INPUT_PULLDOWN);
  pinMode(el_down_limit_pin, INPUT_PULLDOWN);

  // Initialize servos
  az_servo.setPeriodHertz(50);  // Standard RC servo frequency (50 Hz)
  az_servo.attach(az_servo_pin, servo_min_us, servo_max_us);

  el_servo.setPeriodHertz(50);
  el_servo.attach(el_servo_pin, servo_min_us, servo_max_us);

  // Move to home position (0° azimuth, 0° elevation)
  set_position(0.0, 0.0);

  Serial.printf("Azimuth servo: GPIO %d\n", az_servo_pin);
  Serial.printf("Elevation servo: GPIO %d\n", el_servo_pin);
  Serial.printf("Home position: Az=%.1f° El=%.1f°\n", az_angle, el_angle);

  Serial.println("\nLimit switches:");
  Serial.printf("  Az CW limit:  GPIO %d\n", az_cw_limit_pin);
  Serial.printf("  Az CCW limit: GPIO %d\n", az_ccw_limit_pin);
  Serial.printf("  El Up limit:  GPIO %d\n", el_up_limit_pin);
  Serial.printf("  El Down limit: GPIO %d\n", el_down_limit_pin);

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

// Read limit switch states
bool az_cw_limit_active() {
  return digitalRead(az_cw_limit_pin) == HIGH;
}

bool az_ccw_limit_active() {
  return digitalRead(az_ccw_limit_pin) == HIGH;
}

bool el_up_limit_active() {
  return digitalRead(el_up_limit_pin) == HIGH;
}

bool el_down_limit_active() {
  return digitalRead(el_down_limit_pin) == HIGH;
}

// Convert antenna azimuth angle (0-360°) to servo angle (0-180°)
float az_to_servo(float az) {
  // Linear mapping from 0-360° antenna to 0-180° servo
  // Note: Some mechanical designs may need 360° servos or multi-turn servos
  float servo_angle = az_servo_min + (az / 360.0) * (az_servo_max - az_servo_min);

  // Clamp to servo range
  if (servo_angle < 0.0) servo_angle = 0.0;
  if (servo_angle > 180.0) servo_angle = 180.0;

  return servo_angle;
}

// Convert antenna elevation angle (0-90°) to servo angle (0-180°)
float el_to_servo(float el) {
  // Linear mapping from 0-90° antenna to servo range
  float servo_angle = el_servo_min + (el / 90.0) * (el_servo_max - el_servo_min);

  // Clamp to servo range
  if (servo_angle < 0.0) servo_angle = 0.0;
  if (servo_angle > 180.0) servo_angle = 180.0;

  return servo_angle;
}

// Set antenna position with limit switch checking and smooth slewing
void set_position(float target_az, float target_el) {
  if (emergency_stop) {
    Serial.println("Emergency stop active - motion blocked");
    return;
  }

  // Clamp target angles to valid ranges
  if (target_az < 0.0) target_az = 0.0;
  if (target_az > 360.0) target_az = 360.0;
  if (target_el < 0.0) target_el = 0.0;
  if (target_el > 90.0) target_el = 90.0;

  // Calculate step size based on slew speed
  // At 30°/sec with 50ms steps, that's 1.5° per step
  float step_time_ms = 50.0;  // Update every 50ms
  float az_step = slew_speed * (step_time_ms / 1000.0);
  float el_step = slew_speed * (step_time_ms / 1000.0);

  bool moving = true;
  while (moving && !emergency_stop) {
    moving = false;
    float new_az = az_angle;
    float new_el = el_angle;

    // Azimuth motion
    if (abs(target_az - az_angle) > 0.5) {  // 0.5° deadband
      moving = true;
      if (target_az > az_angle) {
        // Moving CW (increasing azimuth)
        if (az_cw_limit_active()) {
          Serial.println("Az CW limit reached - stopping azimuth motion");
          target_az = az_angle;  // Stop at current position
        } else {
          new_az = az_angle + az_step;
          if (new_az > target_az) new_az = target_az;
        }
      } else {
        // Moving CCW (decreasing azimuth)
        if (az_ccw_limit_active()) {
          Serial.println("Az CCW limit reached - stopping azimuth motion");
          target_az = az_angle;  // Stop at current position
        } else {
          new_az = az_angle - az_step;
          if (new_az < target_az) new_az = target_az;
        }
      }
    }

    // Elevation motion
    if (abs(target_el - el_angle) > 0.5) {  // 0.5° deadband
      moving = true;
      if (target_el > el_angle) {
        // Moving up (increasing elevation)
        if (el_up_limit_active()) {
          Serial.println("El Up limit reached - stopping elevation motion");
          target_el = el_angle;  // Stop at current position
        } else {
          new_el = el_angle + el_step;
          if (new_el > target_el) new_el = target_el;
        }
      } else {
        // Moving down (decreasing elevation)
        if (el_down_limit_active()) {
          Serial.println("El Down limit reached - stopping elevation motion");
          target_el = el_angle;  // Stop at current position
        } else {
          new_el = el_angle - el_step;
          if (new_el < target_el) new_el = target_el;
        }
      }
    }

    // Update positions
    az_angle = new_az;
    el_angle = new_el;

    // Convert to servo angles and write
    int az_servo_angle = (int)(az_to_servo(az_angle) + 0.5);
    int el_servo_angle = (int)(el_to_servo(el_angle) + 0.5);

    az_servo.write(az_servo_angle);
    el_servo.write(el_servo_angle);

    if (moving) {
      delay((int)step_time_ms);
    }
  }

  Serial.printf("Position: Az=%.1f° El=%.1f°\n", az_angle, el_angle);
}

// Set azimuth only
void set_azimuth(float az) {
  set_position(az, el_angle);
}

// Set elevation only
void set_elevation(float el) {
  set_position(az_angle, el);
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
    send_response("N0GQ,ESP32-SCPI-Rotator,1.0,2026\n");
  }

  // *RST - Reset (home position: 0° azimuth, 0° elevation)
  else if (strcmp(cmd, "*RST") == 0) {
    emergency_stop = false;
    set_position(0.0, 0.0);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // ROT:AZ,<deg> - Set azimuth (0-360°)
  else if (strncmp(cmd, "ROT:AZ", 6) == 0 || strncmp(cmd, "ROTAT:AZIMUTH", 13) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      float az;
      if (sscanf(comma + 1, "%f", &az) == 1) {
        set_azimuth(az);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid azimuth value\n");
      }
    } else {
      send_response("ERROR: Missing azimuth parameter\n");
    }
  }

  // ROT:AZ? - Query azimuth
  else if (strcmp(cmd, "ROT:AZ?") == 0 || strcmp(cmd, "ROTAT:AZIMUTH?") == 0) {
    snprintf(response, sizeof(response), "%.1f\n", az_angle);
    send_response(response);
  }

  // ROT:EL,<deg> - Set elevation (0-90°)
  else if (strncmp(cmd, "ROT:EL", 6) == 0 || strncmp(cmd, "ROTAT:ELEVATION", 15) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      float el;
      if (sscanf(comma + 1, "%f", &el) == 1) {
        set_elevation(el);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid elevation value\n");
      }
    } else {
      send_response("ERROR: Missing elevation parameter\n");
    }
  }

  // ROT:EL? - Query elevation
  else if (strcmp(cmd, "ROT:EL?") == 0 || strcmp(cmd, "ROTAT:ELEVATION?") == 0) {
    snprintf(response, sizeof(response), "%.1f\n", el_angle);
    send_response(response);
  }

  // ROT:HOME - Move to home position (0°, 0°)
  else if (strcmp(cmd, "ROT:HOME") == 0 || strcmp(cmd, "ROTAT:HOME") == 0) {
    emergency_stop = false;
    set_position(0.0, 0.0);
    send_response("OK\n");
  }

  // ROT:STOP - Emergency stop
  else if (strcmp(cmd, "ROT:STOP") == 0 || strcmp(cmd, "ROTAT:STOP") == 0) {
    emergency_stop = true;
    Serial.println("EMERGENCY STOP");
    send_response("OK\n");
  }

  // ROT:LIM:AZ? - Query azimuth limit switches (bit 0=CW, bit 1=CCW)
  else if (strcmp(cmd, "ROT:LIM:AZ?") == 0 || strcmp(cmd, "ROTAT:LIMIT:AZIMUTH?") == 0) {
    int status = (az_cw_limit_active() ? 1 : 0) | (az_ccw_limit_active() ? 2 : 0);
    snprintf(response, sizeof(response), "%d\n", status);
    send_response(response);
  }

  // ROT:LIM:EL? - Query elevation limit switches (bit 0=Up, bit 1=Down)
  else if (strcmp(cmd, "ROT:LIM:EL?") == 0 || strcmp(cmd, "ROTAT:LIMIT:ELEVATION?") == 0) {
    int status = (el_up_limit_active() ? 1 : 0) | (el_down_limit_active() ? 2 : 0);
    snprintf(response, sizeof(response), "%d\n", status);
    send_response(response);
  }

  // ROT:SPEED,<deg/sec> - Set slew speed
  else if (strncmp(cmd, "ROT:SPEED", 9) == 0 || strncmp(cmd, "ROTAT:SPEED", 11) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      float speed;
      if (sscanf(comma + 1, "%f", &speed) == 1) {
        if (speed > 0.0 && speed <= 180.0) {
          slew_speed = speed;
          snprintf(response, sizeof(response), "OK (speed=%.1f deg/sec)\n", slew_speed);
          send_response(response);
        } else {
          send_response("ERROR: Speed must be 0.1-180.0 deg/sec\n");
        }
      } else {
        send_response("ERROR: Invalid speed value\n");
      }
    } else {
      send_response("ERROR: Missing speed parameter\n");
    }
  }

  // ROT:SPEED? - Query slew speed
  else if (strcmp(cmd, "ROT:SPEED?") == 0 || strcmp(cmd, "ROTAT:SPEED?") == 0) {
    snprintf(response, sizeof(response), "%.1f\n", slew_speed);
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
