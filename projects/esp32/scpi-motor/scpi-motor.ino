/*
 * SCPI DC Motor Controller for ESP32
 *
 * Controls 2 DC motors via L298N H-bridge driver over SCPI commands via TCP/IP
 * Speed control via PWM, direction control via H-bridge logic
 *
 * Hardware connections:
 *   Motor 1:
 *     IN1 -> GPIO 25 (H-bridge input 1)
 *     IN2 -> GPIO 26 (H-bridge input 2)
 *     EN  -> GPIO 27 (PWM enable, controls speed)
 *
 *   Motor 2:
 *     IN1 -> GPIO 14 (H-bridge input 1)
 *     IN2 -> GPIO 32 (H-bridge input 2)
 *     EN  -> GPIO 33 (PWM enable, controls speed)
 *
 *   Driver power:
 *     12V -> L298N VCC pin (motor power supply, 6-35V)
 *     5V  -> L298N 5V pin (logic power, can be from onboard regulator)
 *     GND -> Common ground with ESP32
 *
 * CRITICAL: Motors are powered from external 12V supply, NOT from ESP32.
 * L298N can draw several amps. Share GND with ESP32 for signal reference.
 *
 * H-bridge truth table (per motor):
 *   IN1  IN2  EN   | Result
 *   LOW  LOW  any  | Coast (motor freewheels)
 *   LOW  HIGH PWM  | Forward at PWM speed
 *   HIGH LOW  PWM  | Reverse at PWM speed
 *   HIGH HIGH any  | Brake (both pins HIGH shorts motor terminals)
 *
 * Speed control: PWM on EN pin (0-255 duty cycle)
 * Direction control: IN1/IN2 logic states
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Motor GPIO pins [motor_index]
const int in1_pins[2] = {25, 14};
const int in2_pins[2] = {26, 32};
const int en_pins[2] = {27, 33};
const int num_motors = 2;

// PWM configuration
const int pwm_freq = 1000;      // 1 kHz PWM frequency
const int pwm_resolution = 8;   // 8-bit resolution (0-255)
const int pwm_channels[2] = {0, 1}; // LEDC channels for each motor

// Motor states
struct MotorState {
  int speed;           // Current speed: -100 to +100 (-100 = full reverse, 0 = stop, +100 = full forward)
  bool brake_mode;     // true = brake (both pins HIGH), false = coast (both pins LOW)
};

MotorState motors[2];

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI DC Motor Controller");
  Serial.println("=========================");

  // Initialize motor pins
  for (int i = 0; i < num_motors; i++) {
    pinMode(in1_pins[i], OUTPUT);
    pinMode(in2_pins[i], OUTPUT);
    pinMode(en_pins[i], OUTPUT);

    // Initialize motor state
    motors[i].speed = 0;
    motors[i].brake_mode = false;

    // Set initial pin states (coast)
    digitalWrite(in1_pins[i], LOW);
    digitalWrite(in2_pins[i], LOW);
    digitalWrite(en_pins[i], LOW);

    // Configure PWM channel
    ledcSetup(pwm_channels[i], pwm_freq, pwm_resolution);
    ledcAttachPin(en_pins[i], pwm_channels[i]);
    ledcWrite(pwm_channels[i], 0);

    Serial.printf("Motor %d: IN1=%d, IN2=%d, EN=%d (coast, 0%%)\n",
                  i+1, in1_pins[i], in2_pins[i], en_pins[i]);
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

// Set motor speed and direction
// speed: -100 (full reverse) to +100 (full forward), 0 = stop (coast)
void set_motor_speed(int motor, int speed) {
  if (motor < 0 || motor >= num_motors) return;

  // Clamp speed to valid range
  if (speed < -100) speed = -100;
  if (speed > 100) speed = 100;

  motors[motor].speed = speed;
  motors[motor].brake_mode = false;

  // Calculate PWM duty cycle (0-255)
  int pwm_value = (abs(speed) * 255) / 100;

  // Set direction based on sign
  if (speed > 0) {
    // Forward
    digitalWrite(in1_pins[motor], LOW);
    digitalWrite(in2_pins[motor], HIGH);
  } else if (speed < 0) {
    // Reverse
    digitalWrite(in1_pins[motor], HIGH);
    digitalWrite(in2_pins[motor], LOW);
  } else {
    // Coast (both pins LOW)
    digitalWrite(in1_pins[motor], LOW);
    digitalWrite(in2_pins[motor], LOW);
  }

  // Set PWM speed
  ledcWrite(pwm_channels[motor], pwm_value);

  Serial.printf("Motor %d: speed %d%% (%s)\n",
                motor + 1, speed,
                speed > 0 ? "forward" : (speed < 0 ? "reverse" : "coast"));
}

// Brake motor (both pins HIGH, shorts motor terminals)
void brake_motor(int motor) {
  if (motor < 0 || motor >= num_motors) return;

  motors[motor].speed = 0;
  motors[motor].brake_mode = true;

  digitalWrite(in1_pins[motor], HIGH);
  digitalWrite(in2_pins[motor], HIGH);
  ledcWrite(pwm_channels[motor], 255);

  Serial.printf("Motor %d: brake\n", motor + 1);
}

// Coast motor (both pins LOW, motor freewheels)
void coast_motor(int motor) {
  if (motor < 0 || motor >= num_motors) return;

  motors[motor].speed = 0;
  motors[motor].brake_mode = false;

  digitalWrite(in1_pins[motor], LOW);
  digitalWrite(in2_pins[motor], LOW);
  ledcWrite(pwm_channels[motor], 0);

  Serial.printf("Motor %d: coast\n", motor + 1);
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
    send_response("N0GQ,ESP32-SCPI-Motor,1.0,2026\n");
  }

  // *RST - Reset (all motors coast)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < num_motors; i++) {
      coast_motor(i);
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // MOT:SPEED (@n),<-100..100> - Set motor n speed/direction
  else if (strncmp(cmd, "MOT:SPEED", 9) == 0 && !strstr(cmd, "?")) {
    int motor = parse_motor_number(cmd);
    const char* comma = strchr(cmd, ',');

    if (motor >= 0 && motor < num_motors && comma) {
      int speed;
      if (sscanf(comma + 1, "%d", &speed) == 1) {
        set_motor_speed(motor, speed);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid speed value\n");
      }
    } else {
      send_response("ERROR: Invalid motor number or syntax\n");
    }
  }

  // MOT:SPEED? (@n) - Query motor n speed
  else if (strncmp(cmd, "MOT:SPEED?", 10) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      snprintf(response, sizeof(response), "%d\n", motors[motor].speed);
      send_response(response);
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // MOT:BRA (@n) - Brake motor n (both pins HIGH)
  else if (strncmp(cmd, "MOT:BRA", 7) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      brake_motor(motor);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // MOT:COAS (@n) - Coast motor n (both pins LOW)
  else if (strncmp(cmd, "MOT:COAS", 8) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      coast_motor(motor);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // MOT:STOP (@n) - Stop motor n (alias for brake)
  else if (strncmp(cmd, "MOT:STOP", 8) == 0) {
    int motor = parse_motor_number(cmd);

    if (motor >= 0 && motor < num_motors) {
      brake_motor(motor);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid motor number\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
