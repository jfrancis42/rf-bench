/*
 * SCPI Temperature Monitor for ESP32
 *
 * Reads DS18B20 1-Wire digital temperature sensors and provides SCPI access over TCP/IP
 * Supports up to 16 sensors on a single GPIO pin
 *
 * Hardware connections:
 *   DS18B20 sensors:
 *     VCC (red)    -> 3.3V or 5V (external power recommended for >2 sensors)
 *     GND (black)  -> GND
 *     DATA (yellow) -> GPIO 4 (with 4.7kΩ pull-up resistor to VCC)
 *
 *   Optional (for parasitic power mode - not recommended):
 *     VCC and GND shorted together -> GND
 *     DATA pull-up provides power (works for 1-2 sensors only)
 *
 * 1-Wire bus requires 4.7kΩ pull-up resistor between DATA and VCC.
 * Multiple DS18B20 sensors share the same bus (parallel connection).
 * Each sensor has a unique 64-bit ROM address for identification.
 *
 * Temperature conversion time: ~750ms for 12-bit resolution (default)
 * Temperature range: -55°C to +125°C
 * Accuracy: ±0.5°C from -10°C to +85°C
 * Resolution: 0.0625°C (12-bit)
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

// Maximum number of sensors supported
const int max_sensors = 16;

// Temperature alarm thresholds (per sensor)
float alarm_high[max_sensors];
float alarm_low[max_sensors];
bool alarm_high_enabled[max_sensors];
bool alarm_low_enabled[max_sensors];

// 1-Wire and DallasTemperature objects
OneWire oneWire(onewire_pin);
DallasTemperature sensors(&oneWire);

// Detected sensor addresses (64-bit ROM addresses)
DeviceAddress sensor_addresses[max_sensors];
int sensor_count = 0;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Temperature Monitor");
  Serial.println("========================");

  // Initialize alarm thresholds (disabled by default)
  for (int i = 0; i < max_sensors; i++) {
    alarm_high[i] = 85.0;  // Default high threshold
    alarm_low[i] = 0.0;    // Default low threshold
    alarm_high_enabled[i] = false;
    alarm_low_enabled[i] = false;
  }

  // Start 1-Wire bus
  sensors.begin();

  // Discover sensors
  sensor_count = sensors.getDeviceCount();
  Serial.printf("Found %d DS18B20 sensor(s) on GPIO %d\n", sensor_count, onewire_pin);

  if (sensor_count == 0) {
    Serial.println("\nWARNING: No sensors detected!");
    Serial.println("  - Check wiring (DATA -> GPIO 4)");
    Serial.println("  - Verify 4.7kΩ pull-up resistor between DATA and VCC");
    Serial.println("  - Check sensor power (VCC and GND)");
    Serial.println("  - Try different sensors (sensor may be faulty)");
  } else {
    // Store sensor addresses
    for (int i = 0; i < sensor_count && i < max_sensors; i++) {
      if (sensors.getAddress(sensor_addresses[i], i)) {
        Serial.printf("  Sensor %d: ", i + 1);
        print_address(sensor_addresses[i]);
        Serial.println();
      }
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
  Serial.println("\nReady for SCPI commands");

  // Start SCPI server
  server.begin();

  // Request initial temperature conversion
  sensors.requestTemperatures();
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

// Parse sensor number from SCPI command (e.g., "(@1)" or "(@16)")
int parse_sensor_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int sensor = -1;
  sscanf(at_sign, "@%d", &sensor);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return sensor - 1;
}

// Read temperature from sensor (in Celsius)
float read_temperature(int sensor) {
  if (sensor < 0 || sensor >= sensor_count) return -999.0;

  // Request temperature conversion (blocking for ~750ms)
  sensors.requestTemperatures();

  // Read temperature by address
  float temp = sensors.getTempC(sensor_addresses[sensor]);

  // Check for sensor error (-127.0 indicates sensor not responding)
  if (temp == -127.0 || temp == 85.0) {
    // 85.0 is power-on default; retry once
    delay(10);
    sensors.requestTemperatures();
    temp = sensors.getTempC(sensor_addresses[sensor]);
  }

  return temp;
}

// Check if sensor is in alarm state
bool check_alarm(int sensor, float temp) {
  if (sensor < 0 || sensor >= sensor_count) return false;

  bool alarm = false;

  if (alarm_high_enabled[sensor] && temp > alarm_high[sensor]) {
    alarm = true;
  }

  if (alarm_low_enabled[sensor] && temp < alarm_low[sensor]) {
    alarm = true;
  }

  return alarm;
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
    send_response("N0GQ,ESP32-SCPI-Temperature,1.0,2026\n");
  }

  // *RST - Reset (clear alarms, but don't affect sensors)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < max_sensors; i++) {
      alarm_high_enabled[i] = false;
      alarm_low_enabled[i] = false;
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // TEMP:COUN? - Query number of sensors found
  else if (strcmp(cmd, "TEMP:COUN?") == 0 || strcmp(cmd, "TEMP:COUNT?") == 0) {
    snprintf(response, sizeof(response), "%d\n", sensor_count);
    send_response(response);
  }

  // TEMP:MEAS? (@n) - Read temperature of sensor n in Celsius
  else if (strncmp(cmd, "TEMP:MEAS?", 10) == 0 || strncmp(cmd, "TEMP:MEASURE?", 13) == 0) {
    int sensor = parse_sensor_number(cmd);

    if (sensor >= 0 && sensor < sensor_count) {
      float temp = read_temperature(sensor);

      if (temp == -127.0) {
        send_response("ERROR: Sensor not responding\n");
      } else {
        snprintf(response, sizeof(response), "%.4f\n", temp);
        send_response(response);
      }
    } else {
      send_response("ERROR: Invalid sensor number\n");
    }
  }

  // TEMP:MEAS:F? (@n) - Read temperature in Fahrenheit
  else if (strncmp(cmd, "TEMP:MEAS:F?", 12) == 0 || strncmp(cmd, "TEMP:MEASURE:F?", 15) == 0) {
    int sensor = parse_sensor_number(cmd);

    if (sensor >= 0 && sensor < sensor_count) {
      float temp_c = read_temperature(sensor);

      if (temp_c == -127.0) {
        send_response("ERROR: Sensor not responding\n");
      } else {
        float temp_f = temp_c * 9.0 / 5.0 + 32.0;
        snprintf(response, sizeof(response), "%.4f\n", temp_f);
        send_response(response);
      }
    } else {
      send_response("ERROR: Invalid sensor number\n");
    }
  }

  // TEMP:ALL? - Return CSV of all temperatures
  else if (strcmp(cmd, "TEMP:ALL?") == 0) {
    if (sensor_count == 0) {
      send_response("ERROR: No sensors found\n");
      return;
    }

    // Request all temperatures at once
    sensors.requestTemperatures();

    response[0] = '\0';
    char temp_str[16];

    for (int i = 0; i < sensor_count; i++) {
      float temp = sensors.getTempC(sensor_addresses[i]);
      snprintf(temp_str, sizeof(temp_str), "%.4f", temp);
      strcat(response, temp_str);

      if (i < sensor_count - 1) {
        strcat(response, ",");
      }
    }

    strcat(response, "\n");
    send_response(response);
  }

  // TEMP:ADDR? (@n) - Return 64-bit ROM address of sensor n
  else if (strncmp(cmd, "TEMP:ADDR?", 10) == 0 || strncmp(cmd, "TEMP:ADDRESS?", 13) == 0) {
    int sensor = parse_sensor_number(cmd);

    if (sensor >= 0 && sensor < sensor_count) {
      response[0] = '\0';
      char byte_str[3];

      for (int i = 0; i < 8; i++) {
        snprintf(byte_str, sizeof(byte_str), "%02X", sensor_addresses[sensor][i]);
        strcat(response, byte_str);
      }

      strcat(response, "\n");
      send_response(response);
    } else {
      send_response("ERROR: Invalid sensor number\n");
    }
  }

  // TEMP:ALAR:HIGH (@n),<temp> - Set high alarm threshold
  else if (strncmp(cmd, "TEMP:ALAR:HIGH", 14) == 0 || strncmp(cmd, "TEMP:ALARM:HIGH", 15) == 0) {
    int sensor = parse_sensor_number(cmd);

    if (sensor >= 0 && sensor < sensor_count) {
      // Find the comma after (@n)
      const char* comma = strchr(cmd, ',');

      if (comma) {
        float threshold;
        if (sscanf(comma + 1, "%f", &threshold) == 1) {
          alarm_high[sensor] = threshold;
          alarm_high_enabled[sensor] = true;
          send_response("OK\n");
        } else {
          send_response("ERROR: Invalid threshold value\n");
        }
      } else {
        send_response("ERROR: Missing threshold parameter\n");
      }
    } else {
      send_response("ERROR: Invalid sensor number\n");
    }
  }

  // TEMP:ALAR:LOW (@n),<temp> - Set low alarm threshold
  else if (strncmp(cmd, "TEMP:ALAR:LOW", 13) == 0 || strncmp(cmd, "TEMP:ALARM:LOW", 14) == 0) {
    int sensor = parse_sensor_number(cmd);

    if (sensor >= 0 && sensor < sensor_count) {
      // Find the comma after (@n)
      const char* comma = strchr(cmd, ',');

      if (comma) {
        float threshold;
        if (sscanf(comma + 1, "%f", &threshold) == 1) {
          alarm_low[sensor] = threshold;
          alarm_low_enabled[sensor] = true;
          send_response("OK\n");
        } else {
          send_response("ERROR: Invalid threshold value\n");
        }
      } else {
        send_response("ERROR: Missing threshold parameter\n");
      }
    } else {
      send_response("ERROR: Invalid sensor number\n");
    }
  }

  // TEMP:ALAR? (@n) - Query if sensor is in alarm state
  else if (strncmp(cmd, "TEMP:ALAR?", 10) == 0 || strncmp(cmd, "TEMP:ALARM?", 11) == 0) {
    int sensor = parse_sensor_number(cmd);

    if (sensor >= 0 && sensor < sensor_count) {
      float temp = read_temperature(sensor);

      if (temp == -127.0) {
        send_response("ERROR: Sensor not responding\n");
      } else {
        bool alarm = check_alarm(sensor, temp);
        send_response(alarm ? "1\n" : "0\n");
      }
    } else {
      send_response("ERROR: Invalid sensor number\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
