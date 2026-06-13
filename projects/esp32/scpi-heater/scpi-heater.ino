/*
 * SCPI PID Temperature Controller for ESP32
 *
 * Closed-loop temperature control with DS18B20 sensor and SSR heater output
 * PID algorithm maintains target temperature with proportional control
 *
 * Hardware connections:
 *   DS18B20 sensor:
 *     VCC (red)    -> 3.3V or 5V
 *     GND (black)  -> GND
 *     DATA (yellow) -> GPIO 4 (with 4.7kΩ pull-up resistor to VCC)
 *
 *   SSR heater control:
 *     GPIO 25 -> SSR control input (3.3V logic, 0-100% PWM for proportional control)
 *     SSR output -> Heater load (120/240VAC)
 *
 * 1-Wire bus requires 4.7kΩ pull-up resistor between DATA and VCC.
 * SSR (Solid State Relay) allows proportional control via PWM input.
 *
 * Temperature conversion time: ~750ms for 12-bit resolution
 * PID update rate: 1 Hz (once per second)
 * Temperature range: -55°C to +125°C (DS18B20 limit)
 * Heater output: 0-100% duty cycle via PWM
 */

#include <WiFi.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// 1-Wire bus GPIO
const int onewire_pin = 4;

// SSR heater control GPIO
const int ssr_pin = 25;

// PWM configuration for SSR
const int pwm_channel = 0;
const int pwm_frequency = 1;  // 1 Hz (slow PWM for heater control)
const int pwm_resolution = 8; // 8-bit (0-255)

// PID state
float setpoint = 25.0;          // Target temperature (°C)
float kp = 10.0;                // Proportional gain
float ki = 0.5;                 // Integral gain
float kd = 1.0;                 // Derivative gain
bool control_enabled = false;   // PID control enabled
float integral = 0.0;           // Integral accumulator
float prev_error = 0.0;         // Previous error for derivative
float output = 0.0;             // Current heater output (0-100%)
float current_temp = 0.0;       // Last measured temperature (°C)

// PID limits
const float integral_limit = 100.0;  // Anti-windup limit
const float output_min = 0.0;        // Minimum output (0%)
const float output_max = 100.0;      // Maximum output (100%)

// 1-Wire and DallasTemperature objects
OneWire oneWire(onewire_pin);
DallasTemperature sensors(&oneWire);

// DS18B20 sensor address (supports single sensor)
DeviceAddress sensor_address;
bool sensor_found = false;

// PID update timing
unsigned long last_pid_update = 0;
const unsigned long pid_interval = 1000;  // 1 second (1 Hz)

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI PID Temperature Controller");
  Serial.println("================================");

  // Configure SSR PWM output
  pinMode(ssr_pin, OUTPUT);
  ledcSetup(pwm_channel, pwm_frequency, pwm_resolution);
  ledcAttachPin(ssr_pin, pwm_channel);
  ledcWrite(pwm_channel, 0);  // Start with heater OFF
  Serial.printf("SSR control on GPIO %d (PWM channel %d)\n", ssr_pin, pwm_channel);

  // Start 1-Wire bus
  sensors.begin();

  // Discover sensor
  int sensor_count = sensors.getDeviceCount();
  Serial.printf("Found %d DS18B20 sensor(s) on GPIO %d\n", sensor_count, onewire_pin);

  if (sensor_count == 0) {
    Serial.println("\nWARNING: No sensors detected!");
    Serial.println("  - Check wiring (DATA -> GPIO 4)");
    Serial.println("  - Verify 4.7kΩ pull-up resistor between DATA and VCC");
    Serial.println("  - Check sensor power (VCC and GND)");
    sensor_found = false;
  } else {
    // Use first sensor
    if (sensors.getAddress(sensor_address, 0)) {
      sensor_found = true;
      Serial.printf("  Sensor: ");
      print_address(sensor_address);
      Serial.println();
    } else {
      sensor_found = false;
      Serial.println("ERROR: Failed to read sensor address");
    }
  }

  // Set resolution to 12-bit (0.0625°C precision)
  sensors.setResolution(12);

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
  Serial.printf("PID update rate: %lu ms\n", pid_interval);
  Serial.println("\nReady for SCPI commands");

  // Start SCPI server
  server.begin();

  // Initial temperature reading
  if (sensor_found) {
    sensors.requestTemperatures();
    current_temp = sensors.getTempC(sensor_address);
    if (current_temp != -127.0 && current_temp != 85.0) {
      Serial.printf("Initial temperature: %.2f°C\n", current_temp);
    }
  }
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

  // PID control loop (1 Hz update rate)
  unsigned long now = millis();
  if (now - last_pid_update >= pid_interval) {
    last_pid_update = now;

    if (sensor_found && control_enabled) {
      // Read current temperature
      sensors.requestTemperatures();
      current_temp = sensors.getTempC(sensor_address);

      // Check for sensor error
      if (current_temp == -127.0 || current_temp == 85.0) {
        // Retry once
        delay(10);
        sensors.requestTemperatures();
        current_temp = sensors.getTempC(sensor_address);

        if (current_temp == -127.0 || current_temp == 85.0) {
          // Sensor error - disable control for safety
          control_enabled = false;
          set_heater_output(0.0);
          Serial.println("ERROR: Sensor not responding - control disabled");
          return;
        }
      }

      // Calculate PID
      float error = setpoint - current_temp;

      // Proportional term
      float p_term = kp * error;

      // Integral term (with anti-windup)
      integral += error * (pid_interval / 1000.0);  // Convert ms to seconds
      if (integral > integral_limit) integral = integral_limit;
      if (integral < -integral_limit) integral = -integral_limit;
      float i_term = ki * integral;

      // Derivative term
      float derivative = (error - prev_error) / (pid_interval / 1000.0);
      float d_term = kd * derivative;
      prev_error = error;

      // Total PID output
      output = p_term + i_term + d_term;

      // Clamp output to 0-100%
      if (output < output_min) output = output_min;
      if (output > output_max) output = output_max;

      // Apply to heater
      set_heater_output(output);

      // Debug output
      Serial.printf("T=%.2f°C SP=%.2f°C E=%.2f OUT=%.1f%% (P=%.1f I=%.1f D=%.1f)\n",
                    current_temp, setpoint, error, output, p_term, i_term, d_term);
    }
  }
}

// Print DS18B20 address in hex format
void print_address(DeviceAddress addr) {
  for (int i = 0; i < 8; i++) {
    if (addr[i] < 16) Serial.print("0");
    Serial.print(addr[i], HEX);
  }
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Set heater output (0-100%)
void set_heater_output(float percent) {
  if (percent < 0.0) percent = 0.0;
  if (percent > 100.0) percent = 100.0;

  // Convert percentage to PWM value (0-255 for 8-bit)
  int pwm_value = (int)((percent / 100.0) * 255);
  ledcWrite(pwm_channel, pwm_value);
}

// Read temperature from sensor (in Celsius)
float read_temperature() {
  if (!sensor_found) return -999.0;

  // Request temperature conversion (blocking for ~750ms)
  sensors.requestTemperatures();

  // Read temperature
  float temp = sensors.getTempC(sensor_address);

  // Check for sensor error (-127.0 indicates sensor not responding)
  if (temp == -127.0 || temp == 85.0) {
    // 85.0 is power-on default; retry once
    delay(10);
    sensors.requestTemperatures();
    temp = sensors.getTempC(sensor_address);
  }

  return temp;
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

  char response[256];

  // *IDN? - Identification query
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-Heater,1.0,2026\n");
  }

  // *RST - Reset (disable control, reset PID state)
  else if (strcmp(cmd, "*RST") == 0) {
    control_enabled = false;
    integral = 0.0;
    prev_error = 0.0;
    output = 0.0;
    set_heater_output(0.0);
    setpoint = 25.0;
    kp = 10.0;
    ki = 0.5;
    kd = 1.0;
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    if (!sensor_found) {
      send_response("1,\"Sensor not found\"\n");
    } else {
      send_response("0,\"No error\"\n");
    }
  }

  // HEAT:TEMP? - Read current temperature
  else if (strcmp(cmd, "HEAT:TEMP?") == 0) {
    if (!sensor_found) {
      send_response("ERROR: No sensor\n");
    } else {
      float temp = read_temperature();
      if (temp == -127.0) {
        send_response("ERROR: Sensor not responding\n");
      } else {
        snprintf(response, sizeof(response), "%.4f\n", temp);
        send_response(response);
      }
    }
  }

  // HEAT:SETP,<degC> - Set target temperature
  else if (strncmp(cmd, "HEAT:SETP", 9) == 0 && strchr(cmd, ',')) {
    const char* comma = strchr(cmd, ',');
    float new_setpoint;
    if (sscanf(comma + 1, "%f", &new_setpoint) == 1) {
      // Clamp to DS18B20 range
      if (new_setpoint < -55.0) new_setpoint = -55.0;
      if (new_setpoint > 125.0) new_setpoint = 125.0;
      setpoint = new_setpoint;
      // Reset integral when setpoint changes
      integral = 0.0;
      prev_error = 0.0;
      send_response("OK\n");
      Serial.printf("Setpoint changed to %.2f°C\n", setpoint);
    } else {
      send_response("ERROR: Invalid setpoint value\n");
    }
  }

  // HEAT:SETP? - Query setpoint
  else if (strcmp(cmd, "HEAT:SETP?") == 0) {
    snprintf(response, sizeof(response), "%.4f\n", setpoint);
    send_response(response);
  }

  // HEAT:OUT? - Query heater output (0-100%)
  else if (strcmp(cmd, "HEAT:OUT?") == 0) {
    snprintf(response, sizeof(response), "%.2f\n", output);
    send_response(response);
  }

  // HEAT:PID,<P>,<I>,<D> - Set PID constants
  else if (strncmp(cmd, "HEAT:PID", 8) == 0 && strchr(cmd, ',')) {
    const char* first_comma = strchr(cmd, ',');
    if (first_comma) {
      const char* second_comma = strchr(first_comma + 1, ',');
      if (second_comma) {
        float new_kp, new_ki, new_kd;
        if (sscanf(first_comma + 1, "%f,%f,%f", &new_kp, &new_ki, &new_kd) == 3) {
          kp = new_kp;
          ki = new_ki;
          kd = new_kd;
          // Reset integral when gains change
          integral = 0.0;
          prev_error = 0.0;
          send_response("OK\n");
          Serial.printf("PID constants: Kp=%.2f Ki=%.2f Kd=%.2f\n", kp, ki, kd);
        } else {
          send_response("ERROR: Invalid PID values\n");
        }
      } else {
        send_response("ERROR: Missing PID parameters\n");
      }
    } else {
      send_response("ERROR: Missing PID parameters\n");
    }
  }

  // HEAT:PID? - Query PID constants
  else if (strcmp(cmd, "HEAT:PID?") == 0) {
    snprintf(response, sizeof(response), "%.4f,%.4f,%.4f\n", kp, ki, kd);
    send_response(response);
  }

  // HEAT:EN,<0|1> - Enable/disable control
  else if (strncmp(cmd, "HEAT:EN", 7) == 0 && strchr(cmd, ',')) {
    const char* comma = strchr(cmd, ',');
    int enable;
    if (sscanf(comma + 1, "%d", &enable) == 1) {
      if (enable == 0) {
        control_enabled = false;
        integral = 0.0;
        prev_error = 0.0;
        output = 0.0;
        set_heater_output(0.0);
        send_response("OK\n");
        Serial.println("Control disabled");
      } else if (enable == 1) {
        if (!sensor_found) {
          send_response("ERROR: No sensor\n");
        } else {
          control_enabled = true;
          integral = 0.0;
          prev_error = 0.0;
          send_response("OK\n");
          Serial.println("Control enabled");
        }
      } else {
        send_response("ERROR: Invalid enable value (use 0 or 1)\n");
      }
    } else {
      send_response("ERROR: Invalid enable value\n");
    }
  }

  // HEAT:EN? - Query enabled state
  else if (strcmp(cmd, "HEAT:EN?") == 0) {
    send_response(control_enabled ? "1\n" : "0\n");
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
