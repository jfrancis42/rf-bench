/*
 * SCPI DAC Controller for ESP32
 *
 * Controls MCP4728 4-channel 12-bit I2C DAC for arbitrary voltage generation
 * Provides SCPI access over TCP/IP
 *
 * Hardware connections:
 *   MCP4728 -> ESP32
 *     VCC -> 5V (or 3.3V, determines output range)
 *     GND -> GND
 *     SDA -> GPIO 21 (I2C SDA)
 *     SCL -> GPIO 22 (I2C SCL)
 *     LDAC -> GND (immediate update on write)
 *     ADDR -> GND (I2C address 0x60, default)
 *
 * MCP4728 features:
 *   - 4 independent 12-bit DAC channels (0-4095)
 *   - Rail-to-rail output (0 to VDD)
 *   - Internal 2.048V reference or external Vref
 *   - Nonvolatile EEPROM for power-on defaults
 *   - 22 mA max output current per channel
 *
 * Output voltage calculation:
 *   Vout = (DAC_value / 4095) * Vref
 *   Internal Vref: 2.048V (0-2.048V output)
 *   External Vref (VDD): 3.3V or 5V (0-3.3V or 0-5V output)
 *
 * Install library: Adafruit MCP4728 (via Arduino Library Manager)
 */

#include <WiFi.h>
#include <Adafruit_MCP4728.h>
#include <Wire.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// I2C pins (ESP32 default)
const int i2c_sda = 21;
const int i2c_scl = 22;

// MCP4728 object
Adafruit_MCP4728 mcp;

// Current Vref mode per channel (MCP4728_VREF_INTERNAL or MCP4728_VREF_VDD)
MCP4728_channel_t vref_mode[4] = {
  MCP4728_VREF_VDD,
  MCP4728_VREF_VDD,
  MCP4728_VREF_VDD,
  MCP4728_VREF_VDD
};

// Current gain per channel (MCP4728_GAIN_1X or MCP4728_GAIN_2X)
// Gain only applies when using internal Vref (2.048V * 2 = 4.096V)
MCP4728_gain_t gain_mode[4] = {
  MCP4728_GAIN_1X,
  MCP4728_GAIN_1X,
  MCP4728_GAIN_1X,
  MCP4728_GAIN_1X
};

// Current DAC raw values (0-4095)
uint16_t dac_values[4] = {0, 0, 0, 0};

// VDD voltage for external Vref (measured, update if using 3.3V or 5V)
float vdd_voltage = 3.3;  // Default 3.3V, change to 5.0 if using 5V supply

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI DAC Controller");
  Serial.println("===================");

  // Initialize I2C
  Wire.begin(i2c_sda, i2c_scl);
  Serial.printf("I2C: SDA=%d, SCL=%d\n", i2c_sda, i2c_scl);

  // Initialize MCP4728
  if (!mcp.begin()) {
    Serial.println("ERROR: MCP4728 not found!");
    Serial.println("Check wiring and I2C address (0x60 default)");
    while (1) {
      delay(1000);
    }
  }

  Serial.println("MCP4728 initialized at 0x60");
  Serial.printf("VDD voltage: %.2fV (update vdd_voltage in code if using 5V)\n", vdd_voltage);

  // Set all channels to 0V on startup
  for (int ch = 0; ch < 4; ch++) {
    mcp.setChannelValue((MCP4728_channel_t)ch, 0, vref_mode[ch], gain_mode[ch]);
  }

  Serial.println("All channels set to 0V");

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
  Serial.println("Use DAC:VOLT (@n),<volts> to set channel voltage");
  Serial.println("Use DAC:RAW (@n),<0-4095> to set raw DAC value");

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

// Parse channel number from SCPI command (e.g., "(@1)" or "(@4)")
int parse_channel_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int channel = -1;
  sscanf(at_sign, "@%d", &channel);

  // Convert from 1-indexed (SCPI) to 0-indexed (array)
  return channel - 1;
}

// Get current Vref voltage for a channel
float get_vref_voltage(int ch) {
  if (ch < 0 || ch > 3) return 0.0;

  if (vref_mode[ch] == MCP4728_VREF_INTERNAL) {
    // Internal Vref is 2.048V, gain can be 1x or 2x
    if (gain_mode[ch] == MCP4728_GAIN_2X) {
      return 4.096;  // 2.048V * 2
    } else {
      return 2.048;
    }
  } else {
    // External Vref uses VDD (3.3V or 5V)
    return vdd_voltage;
  }
}

// Convert DAC raw value to voltage
float raw_to_voltage(int ch, uint16_t raw) {
  float vref = get_vref_voltage(ch);
  return (raw / 4095.0) * vref;
}

// Convert voltage to DAC raw value
uint16_t voltage_to_raw(int ch, float volts) {
  float vref = get_vref_voltage(ch);
  uint16_t raw = (uint16_t)((volts / vref) * 4095.0);
  if (raw > 4095) raw = 4095;  // Clamp to max
  return raw;
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
    send_response("N0GQ,ESP32-SCPI-DAC,1.0,2026\n");
  }

  // *RST - Reset (all channels to 0V)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int ch = 0; ch < 4; ch++) {
      dac_values[ch] = 0;
      vref_mode[ch] = MCP4728_VREF_VDD;
      gain_mode[ch] = MCP4728_GAIN_1X;
      mcp.setChannelValue((MCP4728_channel_t)ch, 0, vref_mode[ch], gain_mode[ch]);
    }
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // DAC:VOLT (@n),<volts> - Set channel voltage
  else if (strncmp(cmd, "DAC:VOLT", 8) == 0 || strncmp(cmd, "DAC:VOLTAGE", 11) == 0) {
    int ch = parse_channel_number(cmd);

    if (ch >= 0 && ch <= 3) {
      // Find the comma after (@n)
      const char* comma = strchr(cmd, ',');

      if (comma) {
        float volts;
        if (sscanf(comma + 1, "%f", &volts) == 1) {
          float max_volts = get_vref_voltage(ch);

          if (volts < 0.0) {
            send_response("ERROR: Voltage cannot be negative\n");
          } else if (volts > max_volts) {
            snprintf(response, sizeof(response), "ERROR: Voltage exceeds Vref (%.3fV)\n", max_volts);
            send_response(response);
          } else {
            uint16_t raw = voltage_to_raw(ch, volts);
            dac_values[ch] = raw;
            mcp.setChannelValue((MCP4728_channel_t)ch, raw, vref_mode[ch], gain_mode[ch]);
            send_response("OK\n");
          }
        } else {
          send_response("ERROR: Invalid voltage value\n");
        }
      } else {
        send_response("ERROR: Missing voltage parameter\n");
      }
    } else {
      send_response("ERROR: Invalid channel (must be 1-4)\n");
    }
  }

  // DAC:VOLT? (@n) - Query channel voltage
  else if (strncmp(cmd, "DAC:VOLT?", 9) == 0 || strncmp(cmd, "DAC:VOLTAGE?", 12) == 0) {
    int ch = parse_channel_number(cmd);

    if (ch >= 0 && ch <= 3) {
      float volts = raw_to_voltage(ch, dac_values[ch]);
      snprintf(response, sizeof(response), "%.4f\n", volts);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel (must be 1-4)\n");
    }
  }

  // DAC:RAW (@n),<0-4095> - Set channel raw value
  else if (strncmp(cmd, "DAC:RAW", 7) == 0) {
    int ch = parse_channel_number(cmd);

    if (ch >= 0 && ch <= 3) {
      // Find the comma after (@n)
      const char* comma = strchr(cmd, ',');

      if (comma) {
        int raw;
        if (sscanf(comma + 1, "%d", &raw) == 1) {
          if (raw < 0 || raw > 4095) {
            send_response("ERROR: Raw value must be 0-4095\n");
          } else {
            dac_values[ch] = (uint16_t)raw;
            mcp.setChannelValue((MCP4728_channel_t)ch, (uint16_t)raw, vref_mode[ch], gain_mode[ch]);
            send_response("OK\n");
          }
        } else {
          send_response("ERROR: Invalid raw value\n");
        }
      } else {
        send_response("ERROR: Missing raw value parameter\n");
      }
    } else {
      send_response("ERROR: Invalid channel (must be 1-4)\n");
    }
  }

  // DAC:RAW? (@n) - Query channel raw value
  else if (strncmp(cmd, "DAC:RAW?", 8) == 0) {
    int ch = parse_channel_number(cmd);

    if (ch >= 0 && ch <= 3) {
      snprintf(response, sizeof(response), "%d\n", dac_values[ch]);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel (must be 1-4)\n");
    }
  }

  // DAC:VREF,<INT|EXT> - Set Vref mode for all channels
  else if (strncmp(cmd, "DAC:VREF,", 9) == 0) {
    const char* mode_str = cmd + 9;

    if (strcmp(mode_str, "INT") == 0 || strcmp(mode_str, "INTERNAL") == 0) {
      for (int ch = 0; ch < 4; ch++) {
        vref_mode[ch] = MCP4728_VREF_INTERNAL;
        mcp.setChannelValue((MCP4728_channel_t)ch, dac_values[ch], vref_mode[ch], gain_mode[ch]);
      }
      send_response("OK\n");
    } else if (strcmp(mode_str, "EXT") == 0 || strcmp(mode_str, "EXTERNAL") == 0) {
      for (int ch = 0; ch < 4; ch++) {
        vref_mode[ch] = MCP4728_VREF_VDD;
        mcp.setChannelValue((MCP4728_channel_t)ch, dac_values[ch], vref_mode[ch], gain_mode[ch]);
      }
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid Vref mode (must be INT or EXT)\n");
    }
  }

  // DAC:VREF? - Query Vref mode
  else if (strcmp(cmd, "DAC:VREF?") == 0) {
    // Report channel 0 Vref (all channels use same mode in this implementation)
    if (vref_mode[0] == MCP4728_VREF_INTERNAL) {
      send_response("INT\n");
    } else {
      send_response("EXT\n");
    }
  }

  // DAC:GAIN (@n),<1|2> - Set gain for internal Vref (channel-specific)
  else if (strncmp(cmd, "DAC:GAIN", 8) == 0) {
    int ch = parse_channel_number(cmd);

    if (ch >= 0 && ch <= 3) {
      const char* comma = strchr(cmd, ',');

      if (comma) {
        int gain;
        if (sscanf(comma + 1, "%d", &gain) == 1) {
          if (gain == 1) {
            gain_mode[ch] = MCP4728_GAIN_1X;
            mcp.setChannelValue((MCP4728_channel_t)ch, dac_values[ch], vref_mode[ch], gain_mode[ch]);
            send_response("OK\n");
          } else if (gain == 2) {
            gain_mode[ch] = MCP4728_GAIN_2X;
            mcp.setChannelValue((MCP4728_channel_t)ch, dac_values[ch], vref_mode[ch], gain_mode[ch]);
            send_response("OK\n");
          } else {
            send_response("ERROR: Gain must be 1 or 2\n");
          }
        } else {
          send_response("ERROR: Invalid gain value\n");
        }
      } else {
        send_response("ERROR: Missing gain parameter\n");
      }
    } else {
      send_response("ERROR: Invalid channel (must be 1-4)\n");
    }
  }

  // DAC:GAIN? (@n) - Query gain
  else if (strncmp(cmd, "DAC:GAIN?", 9) == 0) {
    int ch = parse_channel_number(cmd);

    if (ch >= 0 && ch <= 3) {
      int gain = (gain_mode[ch] == MCP4728_GAIN_2X) ? 2 : 1;
      snprintf(response, sizeof(response), "%d\n", gain);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel (must be 1-4)\n");
    }
  }

  // DAC:ALL,<v1>,<v2>,<v3>,<v4> - Set all channels at once
  else if (strncmp(cmd, "DAC:ALL,", 8) == 0) {
    float v1, v2, v3, v4;
    if (sscanf(cmd + 8, "%f,%f,%f,%f", &v1, &v2, &v3, &v4) == 4) {
      bool error = false;

      // Validate all voltages first
      for (int ch = 0; ch < 4; ch++) {
        float v = (ch == 0) ? v1 : (ch == 1) ? v2 : (ch == 2) ? v3 : v4;
        float max_v = get_vref_voltage(ch);
        if (v < 0.0 || v > max_v) {
          snprintf(response, sizeof(response),
                   "ERROR: Channel %d voltage out of range (0-%.3fV)\n", ch + 1, max_v);
          send_response(response);
          error = true;
          break;
        }
      }

      // Set all channels if no errors
      if (!error) {
        dac_values[0] = voltage_to_raw(0, v1);
        dac_values[1] = voltage_to_raw(1, v2);
        dac_values[2] = voltage_to_raw(2, v3);
        dac_values[3] = voltage_to_raw(3, v4);

        for (int ch = 0; ch < 4; ch++) {
          mcp.setChannelValue((MCP4728_channel_t)ch, dac_values[ch], vref_mode[ch], gain_mode[ch]);
        }

        send_response("OK\n");
      }
    } else {
      send_response("ERROR: Invalid voltage parameters (need 4 values)\n");
    }
  }

  // DAC:ALL? - Query all channel voltages
  else if (strcmp(cmd, "DAC:ALL?") == 0) {
    snprintf(response, sizeof(response), "%.4f,%.4f,%.4f,%.4f\n",
             raw_to_voltage(0, dac_values[0]),
             raw_to_voltage(1, dac_values[1]),
             raw_to_voltage(2, dac_values[2]),
             raw_to_voltage(3, dac_values[3]));
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
