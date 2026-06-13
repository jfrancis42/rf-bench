/*
 * SCPI ADC for ESP32 with ADS1115
 *
 * 16-bit 4-channel analog-to-digital converter with programmable gain amplifier
 * Provides SCPI access over TCP/IP for automated test equipment
 *
 * Hardware connections:
 *   ADS1115 module (I2C):
 *     VDD -> 3.3V (or 5V - ADS1115 is 2.0-5.5V)
 *     GND -> GND
 *     SCL -> GPIO 22 (default I2C clock)
 *     SDA -> GPIO 21 (default I2C data)
 *     ADDR -> GND (sets I2C address to 0x48, default)
 *     ALERT -> not connected (optional interrupt pin)
 *
 *   Analog inputs (differential or single-ended):
 *     AIN0 -> Channel 0 input
 *     AIN1 -> Channel 1 input
 *     AIN2 -> Channel 2 input
 *     AIN3 -> Channel 3 input
 *
 * I2C address: 0x48 (ADDR to GND), 0x49 (ADDR to VDD), 0x4A (ADDR to SDA), 0x4B (ADDR to SCL)
 * Resolution: 16-bit (signed, -32768 to +32767)
 * Full-scale ranges: ±6.144V, ±4.096V, ±2.048V, ±1.024V, ±0.512V, ±0.256V (via PGA gain 2/3, 1, 2, 4, 8, 16)
 * Sample rates: 8, 16, 32, 64, 128, 250, 475, 860 samples/sec
 * Input impedance: 10 MΩ typical
 * Max voltage: VDD + 0.3V (do not exceed VDD on any input!)
 */

#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// I2C pins (ESP32 default)
const int sda_pin = 21;
const int scl_pin = 22;

// ADS1115 I2C address (0x48 = ADDR to GND, default)
const uint8_t ads_address = 0x48;

// ADS1115 object
Adafruit_ADS1115 ads;

// Per-channel gain settings (default: GAIN_ONE = ±4.096V)
// Gain options: GAIN_TWOTHIRDS (±6.144V), GAIN_ONE (±4.096V), GAIN_TWO (±2.048V),
//               GAIN_FOUR (±1.024V), GAIN_EIGHT (±0.512V), GAIN_SIXTEEN (±0.256V)
adsGain_t channel_gain[4] = {GAIN_ONE, GAIN_ONE, GAIN_ONE, GAIN_ONE};

// Sample rate (default: 128 SPS)
// Rate options: 8, 16, 32, 64, 128, 250, 475, 860 SPS
uint16_t sample_rate = 128;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI ADC (ADS1115)");
  Serial.println("==================");

  // Initialize I2C
  Wire.begin(sda_pin, scl_pin);

  // Initialize ADS1115
  if (!ads.begin(ads_address)) {
    Serial.println("\nERROR: ADS1115 not found!");
    Serial.println("  - Check wiring (SDA -> GPIO 21, SCL -> GPIO 22)");
    Serial.println("  - Verify I2C address (default 0x48, ADDR pin to GND)");
    Serial.println("  - Check power (VDD to 3.3V or 5V)");
    Serial.println("\nContinuing anyway (will respond to SCPI, but readings will fail)");
  } else {
    Serial.printf("ADS1115 found at address 0x%02X\n", ads_address);
  }

  // Set default gain and data rate
  ads.setGain(GAIN_ONE);  // ±4.096V
  ads.setDataRate(RATE_ADS1115_128SPS);

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

// Parse channel number from SCPI command (e.g., "(@0)" or "(@3)")
// Returns -1 on error, 0-3 for valid channel
int parse_channel_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int channel = -1;
  sscanf(at_sign, "@%d", &channel);

  // Validate range (0-3)
  if (channel < 0 || channel > 3) return -1;

  return channel;
}

// Parse gain value from command (e.g., ",1" or ",16")
// Returns GAIN enum or -1 on error
int parse_gain_value(const char* cmd) {
  const char* comma = strchr(cmd, ',');
  if (!comma) return -1;

  int gain_val = -1;
  sscanf(comma + 1, "%d", &gain_val);

  // Map integer to adsGain_t enum
  switch (gain_val) {
    case 0:  return GAIN_TWOTHIRDS;  // ±6.144V (gain 2/3)
    case 1:  return GAIN_ONE;        // ±4.096V (gain 1)
    case 2:  return GAIN_TWO;        // ±2.048V (gain 2)
    case 4:  return GAIN_FOUR;       // ±1.024V (gain 4)
    case 8:  return GAIN_EIGHT;      // ±0.512V (gain 8)
    case 16: return GAIN_SIXTEEN;    // ±0.256V (gain 16)
    default: return -1;
  }
}

// Parse sample rate from command (e.g., ",128")
int parse_rate_value(const char* cmd) {
  const char* comma = strchr(cmd, ',');
  if (!comma) return -1;

  int rate = -1;
  sscanf(comma + 1, "%d", &rate);

  return rate;
}

// Convert adsGain_t enum to gain integer for display
int gain_to_int(adsGain_t gain) {
  switch (gain) {
    case GAIN_TWOTHIRDS: return 0;
    case GAIN_ONE:       return 1;
    case GAIN_TWO:       return 2;
    case GAIN_FOUR:      return 4;
    case GAIN_EIGHT:     return 8;
    case GAIN_SIXTEEN:   return 16;
    default:             return 1;
  }
}

// Read voltage from specified channel
float read_voltage(int channel) {
  if (channel < 0 || channel > 3) return 0.0;

  // Set gain for this channel
  ads.setGain(channel_gain[channel]);

  // Read voltage (blocking, takes ~8-125ms depending on sample rate)
  float voltage = 0.0;

  switch (channel) {
    case 0: voltage = ads.readADC_SingleEnded(0) * ads.computeVoltsPerBit(channel_gain[0]); break;
    case 1: voltage = ads.readADC_SingleEnded(1) * ads.computeVoltsPerBit(channel_gain[1]); break;
    case 2: voltage = ads.readADC_SingleEnded(2) * ads.computeVoltsPerBit(channel_gain[2]); break;
    case 3: voltage = ads.readADC_SingleEnded(3) * ads.computeVoltsPerBit(channel_gain[3]); break;
  }

  return voltage;
}

// Read raw ADC counts from specified channel
int16_t read_raw(int channel) {
  if (channel < 0 || channel > 3) return 0;

  // Set gain for this channel
  ads.setGain(channel_gain[channel]);

  // Read raw 16-bit value
  int16_t raw = 0;

  switch (channel) {
    case 0: raw = ads.readADC_SingleEnded(0); break;
    case 1: raw = ads.readADC_SingleEnded(1); break;
    case 2: raw = ads.readADC_SingleEnded(2); break;
    case 3: raw = ads.readADC_SingleEnded(3); break;
  }

  return raw;
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
    send_response("N0GQ,ESP32-SCPI-ADC,1.0,2026\n");
  }

  // *RST - Reset (all channels to GAIN_ONE, 128 SPS)
  else if (strcmp(cmd, "*RST") == 0) {
    for (int i = 0; i < 4; i++) {
      channel_gain[i] = GAIN_ONE;
    }
    sample_rate = 128;
    ads.setGain(GAIN_ONE);
    ads.setDataRate(RATE_ADS1115_128SPS);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // MEAS:VOLT? (@n) - Read channel n voltage
  else if (strncmp(cmd, "MEAS:VOLT?", 10) == 0 || strncmp(cmd, "MEASURE:VOLTAGE?", 16) == 0) {
    int channel = parse_channel_number(cmd);

    if (channel >= 0 && channel <= 3) {
      float voltage = read_voltage(channel);
      snprintf(response, sizeof(response), "%.6f\n", voltage);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel number (must be 0-3)\n");
    }
  }

  // MEAS:VOLT:RAW? (@n) - Read channel n raw ADC value
  else if (strncmp(cmd, "MEAS:VOLT:RAW?", 14) == 0 || strncmp(cmd, "MEASURE:VOLTAGE:RAW?", 20) == 0) {
    int channel = parse_channel_number(cmd);

    if (channel >= 0 && channel <= 3) {
      int16_t raw = read_raw(channel);
      snprintf(response, sizeof(response), "%d\n", raw);
      send_response(response);
    } else {
      send_response("ERROR: Invalid channel number (must be 0-3)\n");
    }
  }

  // MEAS:ALL? - Read all 4 channels as CSV
  else if (strcmp(cmd, "MEAS:ALL?") == 0 || strcmp(cmd, "MEASURE:ALL?") == 0) {
    snprintf(response, sizeof(response), "%.6f,%.6f,%.6f,%.6f\n",
             read_voltage(0),
             read_voltage(1),
             read_voltage(2),
             read_voltage(3));
    send_response(response);
  }

  // ADC:GAIN (@n),<gain> - Set PGA gain for channel n
  else if (strncmp(cmd, "ADC:GAIN", 8) == 0) {
    // Check if this is a query (ends with ?)
    if (strchr(cmd, '?')) {
      // ADC:GAIN? (@n) - Query gain
      int channel = parse_channel_number(cmd);

      if (channel >= 0 && channel <= 3) {
        int gain_val = gain_to_int(channel_gain[channel]);
        snprintf(response, sizeof(response), "%d\n", gain_val);
        send_response(response);
      } else {
        send_response("ERROR: Invalid channel number (must be 0-3)\n");
      }
    } else {
      // ADC:GAIN (@n),<gain> - Set gain
      int channel = parse_channel_number(cmd);
      int gain = parse_gain_value(cmd);

      if (channel >= 0 && channel <= 3 && gain >= 0) {
        channel_gain[channel] = (adsGain_t)gain;
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid channel or gain (valid gains: 0, 1, 2, 4, 8, 16)\n");
      }
    }
  }

  // ADC:RATE,<rate> - Set sample rate for all channels
  else if (strncmp(cmd, "ADC:RATE", 8) == 0) {
    // Check if this is a query
    if (strchr(cmd, '?')) {
      // ADC:RATE? - Query sample rate
      snprintf(response, sizeof(response), "%d\n", sample_rate);
      send_response(response);
    } else {
      // ADC:RATE,<rate> - Set sample rate
      int rate = parse_rate_value(cmd);

      // Map rate to ADS1115 enum
      bool valid = false;

      switch (rate) {
        case 8:
          ads.setDataRate(RATE_ADS1115_8SPS);
          sample_rate = 8;
          valid = true;
          break;
        case 16:
          ads.setDataRate(RATE_ADS1115_16SPS);
          sample_rate = 16;
          valid = true;
          break;
        case 32:
          ads.setDataRate(RATE_ADS1115_32SPS);
          sample_rate = 32;
          valid = true;
          break;
        case 64:
          ads.setDataRate(RATE_ADS1115_64SPS);
          sample_rate = 64;
          valid = true;
          break;
        case 128:
          ads.setDataRate(RATE_ADS1115_128SPS);
          sample_rate = 128;
          valid = true;
          break;
        case 250:
          ads.setDataRate(RATE_ADS1115_250SPS);
          sample_rate = 250;
          valid = true;
          break;
        case 475:
          ads.setDataRate(RATE_ADS1115_475SPS);
          sample_rate = 475;
          valid = true;
          break;
        case 860:
          ads.setDataRate(RATE_ADS1115_860SPS);
          sample_rate = 860;
          valid = true;
          break;
        default:
          valid = false;
      }

      if (valid) {
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid sample rate (valid: 8, 16, 32, 64, 128, 250, 475, 860)\n");
      }
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
