/*
 * SCPI I2C Controller for ESP32
 *
 * I2C master bridge — scan, read, write I2C devices via SCPI commands over TCP/IP
 * Compatible with any I2C slave device (sensors, EEPROMs, RTCs, I/O expanders, etc.)
 *
 * Hardware connections:
 *   I2C Master (ESP32 Wire library):
 *     SDA -> GPIO 21 (default)
 *     SCL -> GPIO 22 (default)
 *     Pull-ups: 4.7k or 10k to 3.3V (often built-in on modules)
 *
 * Common I2C devices:
 *   0x50      AT24C32 EEPROM (32 kbit)
 *   0x68      DS1307/DS3231 RTC
 *   0x76/0x77 BMP280/BME280 temp/pressure/humidity sensor
 *   0x40      PCA9685 16-channel PWM driver
 *   0x20-0x27 PCF8574/MCP23008 I/O expander
 *   0x48-0x4B ADS1115 16-bit ADC
 *   0x3C/0x3D SSD1306 OLED display
 *   0x1E      HMC5883L magnetometer
 *   0x5A      MPU-6050 IMU (accel + gyro)
 *
 * Note: I2C addresses are 7-bit (0x00-0x7F). The Wire library handles
 * read/write bit automatically. Some datasheets list 8-bit addresses
 * (e.g., 0xD0 for DS1307 write, 0xD1 for read) — divide by 2 for 7-bit.
 */

#include <WiFi.h>
#include <Wire.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// I2C pins (ESP32 default)
const int i2c_sda_pin = 21;
const int i2c_scl_pin = 22;

// I2C frequency (Hz)
// 100000 = 100 kHz (standard mode)
// 400000 = 400 kHz (fast mode)
uint32_t i2c_frequency = 100000;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// Response buffer (for large reads)
char response_buffer[512];

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI I2C Controller");
  Serial.println("===================");

  // Initialize I2C
  Wire.begin(i2c_sda_pin, i2c_scl_pin);
  Wire.setClock(i2c_frequency);
  Serial.printf("I2C initialized: SDA=%d, SCL=%d, freq=%d Hz\n",
                i2c_sda_pin, i2c_scl_pin, i2c_frequency);

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

// Send response to client
void send_response(const char* response) {
  if (client && client.connected()) {
    client.print(response);
  }
}

// Scan I2C bus for devices
void scan_i2c() {
  uint8_t addresses[128];
  int count = 0;

  for (uint8_t addr = 0x00; addr <= 0x7F; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      addresses[count++] = addr;
    }
    delay(1); // Small delay between scans
  }

  if (count == 0) {
    send_response("NONE\n");
  } else {
    // Build CSV response
    char buf[512];
    int offset = 0;
    for (int i = 0; i < count; i++) {
      offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", addresses[i]);
      if (i < count - 1) {
        buf[offset++] = ',';
      }
    }
    buf[offset++] = '\n';
    buf[offset] = '\0';
    send_response(buf);
  }
}

// Read bytes from I2C device
void read_i2c(uint8_t addr, uint8_t count) {
  Wire.requestFrom(addr, count);

  if (Wire.available() == 0) {
    send_response("ERROR: No data received\n");
    return;
  }

  // Build hex CSV response
  char buf[512];
  int offset = 0;
  bool first = true;

  while (Wire.available() && offset < sizeof(buf) - 10) {
    uint8_t byte = Wire.read();
    if (!first) {
      buf[offset++] = ',';
    }
    offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", byte);
    first = false;
  }

  buf[offset++] = '\n';
  buf[offset] = '\0';
  send_response(buf);
}

// Write bytes to I2C device
void write_i2c(uint8_t addr, uint8_t* data, int len) {
  Wire.beginTransmission(addr);
  Wire.write(data, len);
  uint8_t result = Wire.endTransmission();

  if (result == 0) {
    send_response("OK\n");
  } else {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: I2C error %d\n", result);
    send_response(buf);
  }
}

// Read from I2C register (write reg address, then read)
void read_i2c_register(uint8_t addr, uint8_t reg, uint8_t count) {
  // Write register address
  Wire.beginTransmission(addr);
  Wire.write(reg);
  uint8_t result = Wire.endTransmission(false); // false = don't send stop (repeated start)

  if (result != 0) {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: Write register failed %d\n", result);
    send_response(buf);
    return;
  }

  // Read data
  Wire.requestFrom(addr, count);

  if (Wire.available() == 0) {
    send_response("ERROR: No data received\n");
    return;
  }

  // Build hex CSV response
  char buf[512];
  int offset = 0;
  bool first = true;

  while (Wire.available() && offset < sizeof(buf) - 10) {
    uint8_t byte = Wire.read();
    if (!first) {
      buf[offset++] = ',';
    }
    offset += snprintf(buf + offset, sizeof(buf) - offset, "0x%02X", byte);
    first = false;
  }

  buf[offset++] = '\n';
  buf[offset] = '\0';
  send_response(buf);
}

// Write to I2C register
void write_i2c_register(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  uint8_t result = Wire.endTransmission();

  if (result == 0) {
    send_response("OK\n");
  } else {
    char buf[64];
    snprintf(buf, sizeof(buf), "ERROR: I2C error %d\n", result);
    send_response(buf);
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
    send_response("N0GQ,ESP32-SCPI-I2C,1.0,2026\n");
  }

  // *RST - Reset (does nothing for I2C bridge)
  else if (strcmp(cmd, "*RST") == 0) {
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // I2C:SCAN? - Scan I2C bus for devices
  else if (strcmp(cmd, "I2C:SCAN?") == 0) {
    scan_i2c();
  }

  // I2C:FREQ <100000|400000> - Set I2C frequency
  else if (strncmp(cmd, "I2C:FREQ", 8) == 0 || strncmp(cmd, "I2C:FREQUENCY", 13) == 0) {
    const char* comma = strchr(cmd, ',');
    if (!comma) comma = strchr(cmd, ' ');

    if (comma) {
      uint32_t freq;
      if (sscanf(comma + 1, "%u", &freq) == 1) {
        if (freq == 100000 || freq == 400000) {
          i2c_frequency = freq;
          Wire.setClock(i2c_frequency);
          send_response("OK\n");
        } else {
          send_response("ERROR: Frequency must be 100000 or 400000\n");
        }
      } else {
        send_response("ERROR: Invalid frequency\n");
      }
    } else {
      send_response("ERROR: Missing frequency parameter\n");
    }
  }

  // I2C:FREQ? - Query I2C frequency
  else if (strcmp(cmd, "I2C:FREQ?") == 0 || strcmp(cmd, "I2C:FREQUENCY?") == 0) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%u\n", i2c_frequency);
    send_response(buf);
  }

  // I2C:READ? <addr>,<count> - Read count bytes from device
  else if (strncmp(cmd, "I2C:READ?", 9) == 0) {
    const char* comma1 = strchr(cmd, ',');
    if (!comma1) {
      send_response("ERROR: Missing parameters (addr,count)\n");
      return;
    }

    // Find first non-whitespace after "I2C:READ?"
    const char* addr_start = cmd + 9;
    while (*addr_start == ' ' || *addr_start == '\t') addr_start++;

    uint32_t addr_val;
    uint8_t count;

    if (sscanf(addr_start, "%i,%hhu", &addr_val, &count) == 2) {
      if (addr_val > 0x7F) {
        send_response("ERROR: Address out of range (0x00-0x7F)\n");
        return;
      }
      read_i2c((uint8_t)addr_val, count);
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // I2C:WRIT <addr>,<byte1>,<byte2>,... - Write bytes to device
  else if (strncmp(cmd, "I2C:WRIT", 8) == 0 || strncmp(cmd, "I2C:WRITE", 9) == 0) {
    const char* params = strchr(cmd, ',');
    if (!params) params = strchr(cmd, ' ');

    if (!params) {
      send_response("ERROR: Missing parameters\n");
      return;
    }

    // Find first parameter (address)
    const char* addr_start = cmd + (strncmp(cmd, "I2C:WRITE", 9) == 0 ? 9 : 8);
    while (*addr_start == ' ' || *addr_start == '\t') addr_start++;

    uint32_t addr_val;
    if (sscanf(addr_start, "%i", &addr_val) != 1 || addr_val > 0x7F) {
      send_response("ERROR: Invalid address\n");
      return;
    }

    // Parse byte values
    uint8_t data[128];
    int count = 0;
    const char* p = strchr(addr_start, ',');

    while (p && count < 128) {
      p++; // Skip comma
      while (*p == ' ' || *p == '\t') p++; // Skip whitespace

      uint32_t byte_val;
      if (sscanf(p, "%i", &byte_val) == 1) {
        if (byte_val > 0xFF) {
          send_response("ERROR: Byte value out of range (0x00-0xFF)\n");
          return;
        }
        data[count++] = (uint8_t)byte_val;
        p = strchr(p, ',');
      } else {
        break;
      }
    }

    if (count == 0) {
      send_response("ERROR: No data to write\n");
      return;
    }

    write_i2c((uint8_t)addr_val, data, count);
  }

  // I2C:READ:REG? <addr>,<reg>,<count> - Read from register
  else if (strncmp(cmd, "I2C:READ:REG?", 13) == 0) {
    const char* params = strchr(cmd, ',');
    if (!params) params = strchr(cmd, ' ');

    if (!params) {
      send_response("ERROR: Missing parameters\n");
      return;
    }

    // Find first parameter (address)
    const char* addr_start = cmd + 13;
    while (*addr_start == ' ' || *addr_start == '\t') addr_start++;

    uint32_t addr_val, reg_val;
    uint8_t count;

    if (sscanf(addr_start, "%i,%i,%hhu", &addr_val, &reg_val, &count) == 3) {
      if (addr_val > 0x7F || reg_val > 0xFF) {
        send_response("ERROR: Address/register out of range\n");
        return;
      }
      read_i2c_register((uint8_t)addr_val, (uint8_t)reg_val, count);
    } else {
      send_response("ERROR: Invalid parameters (need addr,reg,count)\n");
    }
  }

  // I2C:WRIT:REG <addr>,<reg>,<value> - Write to register
  else if (strncmp(cmd, "I2C:WRIT:REG", 12) == 0 || strncmp(cmd, "I2C:WRITE:REG", 13) == 0) {
    const char* params = strchr(cmd, ',');
    if (!params) params = strchr(cmd, ' ');

    if (!params) {
      send_response("ERROR: Missing parameters\n");
      return;
    }

    // Find first parameter (address)
    int cmd_len = (strncmp(cmd, "I2C:WRITE:REG", 13) == 0) ? 13 : 12;
    const char* addr_start = cmd + cmd_len;
    while (*addr_start == ' ' || *addr_start == '\t') addr_start++;

    uint32_t addr_val, reg_val, value_val;

    if (sscanf(addr_start, "%i,%i,%i", &addr_val, &reg_val, &value_val) == 3) {
      if (addr_val > 0x7F || reg_val > 0xFF || value_val > 0xFF) {
        send_response("ERROR: Address/register/value out of range\n");
        return;
      }
      write_i2c_register((uint8_t)addr_val, (uint8_t)reg_val, (uint8_t)value_val);
    } else {
      send_response("ERROR: Invalid parameters (need addr,reg,value)\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
