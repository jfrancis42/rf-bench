/*
 * ESP32 SCPI Electronic Load
 *
 * MOSFET-based programmable DC electronic load with constant current (CC), constant power (CP),
 * constant resistance (CR), and constant voltage (CV) modes. Uses INA219 for voltage/current
 * sensing and DAC output for MOSFET gate control.
 *
 * Hardware connections:
 *   INA219 Module -> ESP32
 *     VCC  -> 3.3V
 *     GND  -> GND
 *     SDA  -> GPIO 21 (I2C data)
 *     SCL  -> GPIO 22 (I2C clock)
 *
 *   INA219 Power Path:
 *     VIN+ -> DUT positive (source under test)
 *     VIN- -> MOSFET drain (load connection)
 *     GND  -> Common ground
 *
 *   MOSFET Driver:
 *     GPIO 25 (DAC1) -> Op-amp input (gate drive scaling)
 *     Op-amp output  -> MOSFET gate (IRF540N or similar N-channel power MOSFET)
 *     MOSFET source  -> Shunt resistor -> GND
 *     MOSFET drain   -> INA219 VIN-
 *
 * Design notes:
 *   - ESP32 DAC: 8-bit, 0-3.3V output
 *   - Op-amp: voltage follower or gain stage to reach MOSFET gate threshold (typically 4-10V)
 *   - MOSFET: IRF540N (100V, 33A, 44mΩ Rdson) or similar logic-level N-channel
 *   - Heatsink: Required for >10W dissipation (MOSFET operates in linear region)
 *   - Protection: Add over-current, over-voltage, over-temperature shutdown
 *
 * Load modes:
 *   CC (Constant Current): Regulate current to setpoint via PID control
 *   CP (Constant Power):   Regulate power (V × I) to setpoint via PID control
 *   CR (Constant Resistance): Regulate to I = V / R via PID control
 *   CV (Constant Voltage):  Regulate voltage to setpoint via PID control
 *
 * INA219 Configuration:
 *   Default I2C address: 0x40
 *   Bus voltage range: 0-26V (32V mode)
 *   Shunt resistor: 0.1Ω (typical INA219 module)
 *   Current range: ±3.2A with 0.1Ω shunt
 *   Resolution: 0.8mA current, 4mV voltage
 *
 * SCPI Commands:
 *   LOAD:MODE,<CC|CP|CR|CV>  Set load mode
 *   LOAD:MODE?               Query load mode
 *   LOAD:EN,<0|1>            Enable/disable load
 *   LOAD:EN?                 Query enable state
 *   LOAD:CURR,<amps>         Set current setpoint (CC mode)
 *   LOAD:CURR?               Query current setpoint
 *   LOAD:POW,<watts>         Set power setpoint (CP mode)
 *   LOAD:POW?                Query power setpoint
 *   LOAD:RES,<ohms>          Set resistance setpoint (CR mode)
 *   LOAD:RES?                Query resistance setpoint
 *   LOAD:VOLT,<volts>        Set voltage setpoint (CV mode)
 *   LOAD:VOLT?               Query voltage setpoint
 *   MEAS:VOLT?               Measure bus voltage
 *   MEAS:CURR?               Measure current
 *   MEAS:POW?                Measure power
 *   MEAS:ALL?                Query V,I,P as CSV
 *   *IDN?                    Identification string
 *   *RST                     Reset to safe state (load off, CC mode, 0A)
 */

#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_INA219.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port
const int scpi_port = 5025;

// Hardware pins
const int dac_pin = 25;        // GPIO 25 = DAC1 (0-3.3V output to MOSFET gate driver)
const int sda_pin = 21;        // ESP32 default I2C SDA
const int scl_pin = 22;        // ESP32 default I2C SCL
const uint8_t ina219_address = 0x40;

// Load modes
enum LoadMode {
  MODE_CC,   // Constant Current
  MODE_CP,   // Constant Power
  MODE_CR,   // Constant Resistance
  MODE_CV    // Constant Voltage
};

const char* mode_names[] = {"CC", "CP", "CR", "CV"};

// Load state structure
struct {
  LoadMode mode;
  bool enabled;

  // Setpoints (user-commanded targets)
  float setpoint_current_a;      // Amps (CC mode)
  float setpoint_power_w;        // Watts (CP mode)
  float setpoint_resistance_ohm; // Ohms (CR mode)
  float setpoint_voltage_v;      // Volts (CV mode)

  // Measured values
  float measured_voltage_v;
  float measured_current_a;
  float measured_power_w;

  // DAC control (0-255)
  uint8_t dac_value;

  // PID controller state
  float pid_integral;
  float pid_last_error;
  unsigned long pid_last_time_ms;

  // PID tuning parameters (aggressive tuning for fast load response)
  float pid_kp;
  float pid_ki;
  float pid_kd;

  bool sensor_valid;
} load_state;

// INA219 sensor object
Adafruit_INA219 ina219;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nESP32 SCPI Electronic Load");
  Serial.println("===========================");

  // Initialize load state to safe defaults
  load_state.mode = MODE_CC;
  load_state.enabled = false;
  load_state.setpoint_current_a = 0.0;
  load_state.setpoint_power_w = 0.0;
  load_state.setpoint_resistance_ohm = 100.0;  // 100Ω default
  load_state.setpoint_voltage_v = 0.0;
  load_state.measured_voltage_v = 0.0;
  load_state.measured_current_a = 0.0;
  load_state.measured_power_w = 0.0;
  load_state.dac_value = 0;
  load_state.pid_integral = 0.0;
  load_state.pid_last_error = 0.0;
  load_state.pid_last_time_ms = millis();

  // PID tuning (aggressive for fast response)
  load_state.pid_kp = 50.0;   // Proportional gain
  load_state.pid_ki = 10.0;   // Integral gain
  load_state.pid_kd = 1.0;    // Derivative gain

  load_state.sensor_valid = false;

  // Initialize DAC (8-bit, 0-3.3V)
  pinMode(dac_pin, OUTPUT);
  dacWrite(dac_pin, 0);  // Start with gate off (0V)
  Serial.printf("DAC: GPIO %d initialized (0-3.3V, 8-bit)\n", dac_pin);

  // Initialize I2C
  Wire.begin(sda_pin, scl_pin);
  Serial.printf("I2C: SDA=%d, SCL=%d\n", sda_pin, scl_pin);

  // Initialize INA219 sensor
  if (ina219.begin(ina219_address, &Wire)) {
    Serial.printf("INA219: Found at 0x%02X\n", ina219_address);
    ina219.setCalibration_32V_2A();  // 32V bus voltage, 2A max current, 0.1Ω shunt
    load_state.sensor_valid = true;
    Serial.println("INA219: Calibrated for 32V, 2A range (0.1Ω shunt)");
  } else {
    Serial.println("ERROR: INA219 not found!");
    Serial.println("Load will not operate without current sensing");
    load_state.sensor_valid = false;
  }

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

  if (load_state.sensor_valid) {
    Serial.println("Electronic load ready (disabled, CC mode, 0A)");
  } else {
    Serial.println("WARNING: Load will not operate without INA219 sensor");
  }

  // Start SCPI server
  server.begin();
}

void loop() {
  // Update measurements and control loop (10ms interval = 100 Hz)
  static unsigned long last_control_loop = 0;
  unsigned long now = millis();

  if (now - last_control_loop >= 10) {
    update_measurements();
    if (load_state.enabled && load_state.sensor_valid) {
      update_control_loop();
    } else {
      // Load disabled or sensor fault: force DAC to zero (safe state)
      load_state.dac_value = 0;
      dacWrite(dac_pin, 0);
      // Reset PID state when disabled
      load_state.pid_integral = 0.0;
      load_state.pid_last_error = 0.0;
    }
    last_control_loop = now;
  }

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
      // Buffer overflow
      else {
        cmd_index = 0;
        memset(cmd_buffer, 0, sizeof(cmd_buffer));
        send_response("ERROR: Command too long\n");
      }
    }
  }
}

// Update voltage/current/power measurements from INA219
void update_measurements() {
  if (!load_state.sensor_valid) return;

  load_state.measured_voltage_v = ina219.getBusVoltage_V();
  load_state.measured_current_a = ina219.getCurrent_mA() / 1000.0;  // Convert mA to A
  load_state.measured_power_w = ina219.getPower_mW() / 1000.0;      // Convert mW to W
}

// PID control loop for all load modes
void update_control_loop() {
  unsigned long now = millis();
  float dt = (now - load_state.pid_last_time_ms) / 1000.0;  // Convert ms to seconds

  if (dt <= 0) return;  // Avoid division by zero

  load_state.pid_last_time_ms = now;

  // Calculate target based on mode
  float target = 0.0;
  float actual = 0.0;

  switch (load_state.mode) {
    case MODE_CC:  // Constant Current
      target = load_state.setpoint_current_a;
      actual = load_state.measured_current_a;
      break;

    case MODE_CP:  // Constant Power
      target = load_state.setpoint_power_w;
      actual = load_state.measured_power_w;
      break;

    case MODE_CR:  // Constant Resistance: I = V / R
      if (load_state.setpoint_resistance_ohm > 0) {
        target = load_state.measured_voltage_v / load_state.setpoint_resistance_ohm;
        actual = load_state.measured_current_a;
      }
      break;

    case MODE_CV:  // Constant Voltage
      target = load_state.setpoint_voltage_v;
      actual = load_state.measured_voltage_v;
      break;
  }

  // Calculate error
  float error = target - actual;

  // PID terms
  float p_term = load_state.pid_kp * error;
  load_state.pid_integral += error * dt;
  float i_term = load_state.pid_ki * load_state.pid_integral;
  float d_term = load_state.pid_kd * (error - load_state.pid_last_error) / dt;

  load_state.pid_last_error = error;

  // PID output
  float pid_output = p_term + i_term + d_term;

  // Convert PID output to DAC value (0-255)
  // Scale factor depends on your hardware (MOSFET sensitivity, op-amp gain, etc.)
  // This is a starting point; adjust in practice
  int new_dac = load_state.dac_value + (int)(pid_output);

  // Clamp to DAC range
  if (new_dac < 0) new_dac = 0;
  if (new_dac > 255) new_dac = 255;

  load_state.dac_value = new_dac;
  dacWrite(dac_pin, load_state.dac_value);

  // Anti-windup: clamp integral if we're saturated
  if (new_dac == 0 || new_dac == 255) {
    load_state.pid_integral *= 0.9;  // Decay integral when saturated
  }
}

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Process SCPI command
void process_scpi_command(char* cmd) {
  // Convert to uppercase
  for (int i = 0; cmd[i]; i++) {
    cmd[i] = toupper(cmd[i]);
  }

  // Trim whitespace
  while (*cmd == ' ' || *cmd == '\t') cmd++;
  int len = strlen(cmd);
  while (len > 0 && (cmd[len-1] == ' ' || cmd[len-1] == '\t')) {
    cmd[--len] = '\0';
  }

  Serial.printf("SCPI: %s\n", cmd);

  char response[256];

  // *IDN? - Identification
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-Load,1.0,2026\n");
  }

  // *RST - Reset to safe state
  else if (strcmp(cmd, "*RST") == 0) {
    load_state.enabled = false;
    load_state.mode = MODE_CC;
    load_state.setpoint_current_a = 0.0;
    load_state.dac_value = 0;
    dacWrite(dac_pin, 0);
    load_state.pid_integral = 0.0;
    load_state.pid_last_error = 0.0;
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    if (!load_state.sensor_valid) {
      send_response("-200,\"INA219 sensor not found\"\n");
    } else {
      send_response("0,\"No error\"\n");
    }
  }

  // LOAD:MODE,<mode> - Set load mode
  else if (strncmp(cmd, "LOAD:MODE,", 10) == 0) {
    const char* mode_str = cmd + 10;

    if (strcmp(mode_str, "CC") == 0) {
      load_state.mode = MODE_CC;
      send_response("OK\n");
    }
    else if (strcmp(mode_str, "CP") == 0) {
      load_state.mode = MODE_CP;
      send_response("OK\n");
    }
    else if (strcmp(mode_str, "CR") == 0) {
      load_state.mode = MODE_CR;
      send_response("OK\n");
    }
    else if (strcmp(mode_str, "CV") == 0) {
      load_state.mode = MODE_CV;
      send_response("OK\n");
    }
    else {
      send_response("ERROR: Invalid mode (use CC, CP, CR, or CV)\n");
    }
  }

  // LOAD:MODE? - Query load mode
  else if (strcmp(cmd, "LOAD:MODE?") == 0) {
    snprintf(response, sizeof(response), "%s\n", mode_names[load_state.mode]);
    send_response(response);
  }

  // LOAD:EN,<0|1> - Enable/disable load
  else if (strncmp(cmd, "LOAD:EN,", 8) == 0) {
    int enable;
    if (sscanf(cmd + 8, "%d", &enable) == 1) {
      if (enable == 0 || enable == 1) {
        load_state.enabled = (enable == 1);
        send_response("OK\n");
      } else {
        send_response("ERROR: Use 0 (disable) or 1 (enable)\n");
      }
    } else {
      send_response("ERROR: Invalid enable value\n");
    }
  }

  // LOAD:EN? - Query enable state
  else if (strcmp(cmd, "LOAD:EN?") == 0) {
    snprintf(response, sizeof(response), "%d\n", load_state.enabled ? 1 : 0);
    send_response(response);
  }

  // LOAD:CURR,<amps> - Set current setpoint
  else if (strncmp(cmd, "LOAD:CURR,", 10) == 0) {
    float amps;
    if (sscanf(cmd + 10, "%f", &amps) == 1) {
      if (amps >= 0.0 && amps <= 3.2) {  // INA219 with 0.1Ω shunt: max 3.2A
        load_state.setpoint_current_a = amps;
        send_response("OK\n");
      } else {
        send_response("ERROR: Current out of range (0-3.2A)\n");
      }
    } else {
      send_response("ERROR: Invalid current value\n");
    }
  }

  // LOAD:CURR? - Query current setpoint
  else if (strcmp(cmd, "LOAD:CURR?") == 0) {
    snprintf(response, sizeof(response), "%.3f\n", load_state.setpoint_current_a);
    send_response(response);
  }

  // LOAD:POW,<watts> - Set power setpoint
  else if (strncmp(cmd, "LOAD:POW,", 9) == 0) {
    float watts;
    if (sscanf(cmd + 9, "%f", &watts) == 1) {
      if (watts >= 0.0 && watts <= 80.0) {  // Reasonable max (26V × 3A ≈ 78W)
        load_state.setpoint_power_w = watts;
        send_response("OK\n");
      } else {
        send_response("ERROR: Power out of range (0-80W)\n");
      }
    } else {
      send_response("ERROR: Invalid power value\n");
    }
  }

  // LOAD:POW? - Query power setpoint
  else if (strcmp(cmd, "LOAD:POW?") == 0) {
    snprintf(response, sizeof(response), "%.2f\n", load_state.setpoint_power_w);
    send_response(response);
  }

  // LOAD:RES,<ohms> - Set resistance setpoint
  else if (strncmp(cmd, "LOAD:RES,", 9) == 0) {
    float ohms;
    if (sscanf(cmd + 9, "%f", &ohms) == 1) {
      if (ohms > 0.0) {  // Resistance must be positive
        load_state.setpoint_resistance_ohm = ohms;
        send_response("OK\n");
      } else {
        send_response("ERROR: Resistance must be positive\n");
      }
    } else {
      send_response("ERROR: Invalid resistance value\n");
    }
  }

  // LOAD:RES? - Query resistance setpoint
  else if (strcmp(cmd, "LOAD:RES?") == 0) {
    snprintf(response, sizeof(response), "%.2f\n", load_state.setpoint_resistance_ohm);
    send_response(response);
  }

  // LOAD:VOLT,<volts> - Set voltage setpoint
  else if (strncmp(cmd, "LOAD:VOLT,", 10) == 0) {
    float volts;
    if (sscanf(cmd + 10, "%f", &volts) == 1) {
      if (volts >= 0.0 && volts <= 26.0) {  // INA219 max bus voltage
        load_state.setpoint_voltage_v = volts;
        send_response("OK\n");
      } else {
        send_response("ERROR: Voltage out of range (0-26V)\n");
      }
    } else {
      send_response("ERROR: Invalid voltage value\n");
    }
  }

  // LOAD:VOLT? - Query voltage setpoint
  else if (strcmp(cmd, "LOAD:VOLT?") == 0) {
    snprintf(response, sizeof(response), "%.3f\n", load_state.setpoint_voltage_v);
    send_response(response);
  }

  // MEAS:VOLT? - Measure voltage
  else if (strcmp(cmd, "MEAS:VOLT?") == 0 || strcmp(cmd, "MEASURE:VOLTAGE?") == 0) {
    if (load_state.sensor_valid) {
      snprintf(response, sizeof(response), "%.4f\n", load_state.measured_voltage_v);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:CURR? - Measure current
  else if (strcmp(cmd, "MEAS:CURR?") == 0 || strcmp(cmd, "MEASURE:CURRENT?") == 0) {
    if (load_state.sensor_valid) {
      snprintf(response, sizeof(response), "%.4f\n", load_state.measured_current_a);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:POW? - Measure power
  else if (strcmp(cmd, "MEAS:POW?") == 0 || strcmp(cmd, "MEASURE:POWER?") == 0) {
    if (load_state.sensor_valid) {
      snprintf(response, sizeof(response), "%.4f\n", load_state.measured_power_w);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:ALL? - Query all measurements (V,A,W as CSV)
  else if (strcmp(cmd, "MEAS:ALL?") == 0 || strcmp(cmd, "MEASURE:ALL?") == 0) {
    if (load_state.sensor_valid) {
      snprintf(response, sizeof(response), "%.4f,%.4f,%.4f\n",
               load_state.measured_voltage_v, load_state.measured_current_a, load_state.measured_power_w);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
