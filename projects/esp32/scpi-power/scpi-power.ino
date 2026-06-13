/*
 * SCPI Power Monitor for ESP32
 *
 * Monitors voltage, current, and power via INA219 sensor and provides SCPI access over TCP/IP
 * Integrates power measurements over time for energy tracking (Wh)
 *
 * Hardware connections:
 *   INA219 Module -> ESP32
 *     VCC  -> 3.3V (or 5V, depending on module)
 *     GND  -> GND
 *     SDA  -> GPIO 21 (I2C data)
 *     SCL  -> GPIO 22 (I2C clock)
 *
 *   INA219 Power Path:
 *     VIN+ -> Positive supply (0-26V)
 *     VIN- -> Load positive (current flows VIN+ -> VIN-)
 *     GND  -> Load negative (return path)
 *
 * INA219 Configuration:
 *   Default I2C address: 0x40 (configurable to 0x41-0x4F via solder jumpers)
 *   Bus voltage range: 0-26V (16V or 32V mode selectable)
 *   Shunt resistor: 0.1Ω (default on most modules)
 *   Current range: ±3.2A with 0.1Ω shunt
 *   Resolution: 0.8mA current, 4mV voltage
 *
 * Use Cases:
 *   - Battery discharge monitoring
 *   - DUT power consumption measurement
 *   - Efficiency testing (input vs output power)
 *   - USB power profiling
 *   - Solar panel/charger monitoring
 *
 * SCPI provides:
 *   - Instantaneous voltage, current, power readings
 *   - Accumulated energy (mWh) with integration over time
 *   - Configurable sampling rate (10-10000ms)
 */

#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_INA219.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// I2C configuration
const int sda_pin = 21;  // ESP32 default I2C SDA
const int scl_pin = 22;  // ESP32 default I2C SCL
const uint8_t ina219_address = 0x40;  // Default I2C address (0x40-0x4F configurable)

// INA219 sensor object
Adafruit_INA219 ina219;

// Measurement data structure
struct {
  float bus_voltage_v;      // Bus voltage (V)
  float shunt_voltage_mv;   // Shunt voltage (mV)
  float current_ma;         // Current (mA)
  float power_mw;           // Power (mW)

  // Energy accumulation
  double energy_mwh;        // Accumulated energy (mWh)
  unsigned long last_sample_ms;  // millis() of last energy sample

  // Sampling configuration
  unsigned int sample_rate_ms;   // Sampling interval (ms)
  unsigned long last_measurement_ms;  // millis() of last measurement

  bool valid;               // True if sensor initialized successfully
} power_data;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Power Monitor");
  Serial.println("==================");

  // Initialize power data structure
  memset(&power_data, 0, sizeof(power_data));
  power_data.sample_rate_ms = 100;  // Default 100ms sampling
  power_data.last_sample_ms = millis();
  power_data.last_measurement_ms = millis();
  power_data.valid = false;

  // Initialize I2C
  Wire.begin(sda_pin, scl_pin);
  Serial.printf("I2C: SDA=%d, SCL=%d\n", sda_pin, scl_pin);

  // Initialize INA219 sensor
  if (ina219.begin(ina219_address, &Wire)) {
    Serial.printf("INA219: Found at 0x%02X\n", ina219_address);

    // Configure INA219 for 32V, 2A range (suitable for most applications)
    // Calibration: 32V bus voltage, 2A current, 0.1Ω shunt
    // This gives ~0.8mA current resolution and 4mV voltage resolution
    ina219.setCalibration_32V_2A();

    power_data.valid = true;
    Serial.println("INA219: Calibrated for 32V, 2A range (0.1Ω shunt)");
  } else {
    Serial.println("ERROR: INA219 not found!");
    Serial.println("Check wiring and I2C address (default 0x40)");
    power_data.valid = false;
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

  if (power_data.valid) {
    Serial.println("Power monitoring active");
  } else {
    Serial.println("WARNING: INA219 sensor not available - check hardware");
  }

  // Start SCPI server
  server.begin();
}

void loop() {
  // Update power measurements at configured sample rate
  if (power_data.valid) {
    unsigned long now = millis();
    if (now - power_data.last_measurement_ms >= power_data.sample_rate_ms) {
      update_power_measurements();
      power_data.last_measurement_ms = now;
    }
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

// Update power measurements from INA219
void update_power_measurements() {
  if (!power_data.valid) return;

  // Read all measurements from INA219
  power_data.shunt_voltage_mv = ina219.getShuntVoltage_mV();
  power_data.bus_voltage_v = ina219.getBusVoltage_V();
  power_data.current_ma = ina219.getCurrent_mA();
  power_data.power_mw = ina219.getPower_mW();

  // Integrate energy (power × time)
  unsigned long now = millis();
  unsigned long delta_ms = now - power_data.last_sample_ms;

  if (delta_ms > 0 && power_data.last_sample_ms > 0) {
    // Energy = Power × Time
    // mWh = mW × hours = mW × (ms / 3600000)
    double delta_hours = delta_ms / 3600000.0;
    double energy_increment_mwh = power_data.power_mw * delta_hours;
    power_data.energy_mwh += energy_increment_mwh;
  }

  power_data.last_sample_ms = now;
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

  char response[256];

  // *IDN? - Identification query
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-Power,1.0,2026\n");
  }

  // *RST - Reset (reset energy accumulator)
  else if (strcmp(cmd, "*RST") == 0) {
    power_data.energy_mwh = 0.0;
    power_data.last_sample_ms = millis();
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    if (!power_data.valid) {
      send_response("-200,\"INA219 sensor not found\"\n");
    } else {
      send_response("0,\"No error\"\n");
    }
  }

  // MEAS:VOLT? - Query bus voltage (V)
  else if (strcmp(cmd, "MEAS:VOLT?") == 0 || strcmp(cmd, "MEASURE:VOLTAGE?") == 0) {
    if (power_data.valid) {
      snprintf(response, sizeof(response), "%.4f\n", power_data.bus_voltage_v);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:CURR? - Query current (mA)
  else if (strcmp(cmd, "MEAS:CURR?") == 0 || strcmp(cmd, "MEASURE:CURRENT?") == 0) {
    if (power_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", power_data.current_ma);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:POW? - Query power (mW)
  else if (strcmp(cmd, "MEAS:POW?") == 0 || strcmp(cmd, "MEASURE:POWER?") == 0) {
    if (power_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", power_data.power_mw);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:ALL? - Query all measurements (V,mA,mW as CSV)
  else if (strcmp(cmd, "MEAS:ALL?") == 0 || strcmp(cmd, "MEASURE:ALL?") == 0) {
    if (power_data.valid) {
      snprintf(response, sizeof(response), "%.4f,%.2f,%.2f\n",
               power_data.bus_voltage_v, power_data.current_ma, power_data.power_mw);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:ENER? - Query accumulated energy (mWh)
  else if (strcmp(cmd, "MEAS:ENER?") == 0 || strcmp(cmd, "MEASURE:ENERGY?") == 0) {
    if (power_data.valid) {
      snprintf(response, sizeof(response), "%.6f\n", power_data.energy_mwh);
      send_response(response);
    } else {
      send_response("ERROR: INA219 sensor not available\n");
    }
  }

  // MEAS:ENER:RES - Reset energy accumulator to zero
  else if (strcmp(cmd, "MEAS:ENER:RES") == 0 || strcmp(cmd, "MEASURE:ENERGY:RESET") == 0) {
    power_data.energy_mwh = 0.0;
    power_data.last_sample_ms = millis();
    send_response("OK\n");
  }

  // MEAS:SAMP:RATE,<ms> - Set sampling interval
  else if (strncmp(cmd, "MEAS:SAMP:RATE", 14) == 0 || strncmp(cmd, "MEASURE:SAMPLE:RATE", 19) == 0) {
    // Find the comma
    const char* comma = strchr(cmd, ',');

    if (comma) {
      unsigned int rate_ms;
      if (sscanf(comma + 1, "%u", &rate_ms) == 1) {
        // Clamp to reasonable range: 10ms to 10000ms
        if (rate_ms < 10) rate_ms = 10;
        if (rate_ms > 10000) rate_ms = 10000;

        power_data.sample_rate_ms = rate_ms;
        snprintf(response, sizeof(response), "OK (rate set to %ums)\n", rate_ms);
        send_response(response);
      } else {
        send_response("ERROR: Invalid sampling rate\n");
      }
    } else {
      send_response("ERROR: Missing sampling rate parameter\n");
    }
  }

  // MEAS:SAMP:RATE? - Query sampling rate
  else if (strcmp(cmd, "MEAS:SAMP:RATE?") == 0 || strcmp(cmd, "MEASURE:SAMPLE:RATE?") == 0) {
    snprintf(response, sizeof(response), "%u\n", power_data.sample_rate_ms);
    send_response(response);
  }

  // MEAS:SHUNT? - Query shunt voltage (mV) - diagnostic/debug only
  else if (strcmp(cmd, "MEAS:SHUNT?") == 0 || strcmp(cmd, "MEASURE:SHUNT?") == 0) {
    if (power_data.valid) {
      snprintf(response, sizeof(response), "%.4f\n", power_data.shunt_voltage_mv);
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
