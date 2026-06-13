/*
 * SCPI SWR/Power Meter for ESP32
 *
 * Measures forward and reflected RF power using AD8307 logarithmic detectors or diode detectors
 * Calculates SWR and provides SCPI access over TCP/IP with calibration table stored in EEPROM
 *
 * Hardware connections:
 *   Forward Power Detector:
 *     AD8307 OUT -> GPIO 36 (ADC1_CH0) - analog voltage proportional to log(RF power)
 *
 *   Reflected Power Detector:
 *     AD8307 OUT -> GPIO 39 (ADC1_CH3) - analog voltage proportional to log(RF power)
 *
 *   AD8307 Specifications:
 *     Output voltage: ~0.025V/dB slope, typical 0.4V @ -75dBm to 2.5V @ +5dBm
 *     Dynamic range: -75dBm to +17dBm (92dB)
 *     Frequency range: DC to 500 MHz
 *     Supply: 4.5-5.5V (use 5V rail, level-shift output to 3.3V for ESP32 ADC)
 *
 *   Diode Detector Alternative (simple but nonlinear):
 *     RF IN -> Schottky diode (1N5711, BAT46, etc.) -> 10nF -> GPIO 36/39
 *     Ground -> 100kΩ -> GPIO 36/39 (DC return path)
 *     (Requires calibration at multiple power levels due to square-law region)
 *
 * ESP32 ADC Configuration:
 *   ADC1_CH0 (GPIO 36) - forward power detector
 *   ADC1_CH3 (GPIO 39) - reflected power detector
 *   Resolution: 12-bit (0-4095 counts)
 *   Voltage range: 0-3.3V (use 11dB attenuation for 0-3.9V if needed)
 *   Reference: internal 1.1V with attenuation
 *
 * Calibration:
 *   Stores up to 16 calibration points per channel (FWD/REF)
 *   Each point: (raw ADC value, power in dBm)
 *   Linear interpolation between points
 *   Extrapolation beyond range uses nearest point slope
 *   Calibration data saved to EEPROM/NVS, survives reboots
 *
 * SWR Calculation:
 *   SWR = (1 + sqrt(P_ref/P_fwd)) / (1 - sqrt(P_ref/P_fwd))
 *   Equivalent: SWR = (1 + Γ) / (1 - Γ) where Γ = sqrt(P_ref/P_fwd)
 *
 * Use Cases:
 *   - Antenna tuner adjustment
 *   - Transmission line fault detection
 *   - Amplifier output monitoring
 *   - Automated antenna sweeping
 *   - Integration with antenna analyzers
 */

#include <WiFi.h>
#include <Preferences.h>  // ESP32 NVS (non-volatile storage) for calibration

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// ADC pins (ADC1 only - ADC2 conflicts with WiFi)
const int fwd_adc_pin = 36;  // GPIO 36 = ADC1_CH0
const int ref_adc_pin = 39;  // GPIO 39 = ADC1_CH3

// ADC configuration
const int adc_resolution = 12;  // 12-bit = 0-4095
const int adc_samples = 10;     // Number of samples to average per reading

// Calibration table limits
const int max_cal_points = 16;  // Maximum calibration points per channel

// Power unit (DBM or WATT)
enum PowerUnit {
  UNIT_DBM,
  UNIT_WATT
};

PowerUnit power_unit = UNIT_DBM;

// Calibration point structure
struct CalPoint {
  int raw;      // Raw ADC value (0-4095)
  float dbm;    // Power in dBm
};

// Calibration tables (one per channel)
struct CalTable {
  int count;                        // Number of valid calibration points
  CalPoint points[max_cal_points];  // Calibration points, sorted by raw value
};

CalTable fwd_cal;  // Forward power calibration
CalTable ref_cal;  // Reflected power calibration

// Preferences object for NVS storage
Preferences preferences;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI SWR/Power Meter");
  Serial.println("====================");

  // Initialize ADC
  analogReadResolution(adc_resolution);
  analogSetAttenuation(ADC_11db);  // 0-3.9V range (use ADC_6db for 0-2.2V if needed)

  Serial.printf("ADC: FWD on GPIO %d, REF on GPIO %d\n", fwd_adc_pin, ref_adc_pin);
  Serial.printf("ADC resolution: %d-bit (%d max)\n", adc_resolution, (1 << adc_resolution) - 1);

  // Initialize calibration tables
  fwd_cal.count = 0;
  ref_cal.count = 0;

  // Load calibration from NVS
  load_calibration();

  Serial.printf("Calibration loaded: FWD %d points, REF %d points\n", fwd_cal.count, ref_cal.count);

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
  Serial.println("Use POW:FWD? and POW:REF? to read power");
  Serial.println("Use SWR? to calculate SWR");
  Serial.println("Use CAL:FWD,<raw>,<dbm> and CAL:REF,<raw>,<dbm> to calibrate");
  Serial.println("Use CAL:SAV to save calibration to EEPROM");

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

// Read raw ADC value with averaging
int read_adc(int pin) {
  long sum = 0;
  for (int i = 0; i < adc_samples; i++) {
    sum += analogRead(pin);
    delayMicroseconds(100);  // Small delay between samples
  }
  return sum / adc_samples;
}

// Linear interpolation between two calibration points
float interpolate(int raw, CalPoint p1, CalPoint p2) {
  // Linear interpolation: dbm = dbm1 + (raw - raw1) * (dbm2 - dbm1) / (raw2 - raw1)
  if (p2.raw == p1.raw) return p1.dbm;  // Avoid divide by zero
  return p1.dbm + (float)(raw - p1.raw) * (p2.dbm - p1.dbm) / (float)(p2.raw - p1.raw);
}

// Convert raw ADC value to dBm using calibration table
float raw_to_dbm(CalTable& cal, int raw) {
  // No calibration points - return error value
  if (cal.count == 0) {
    return -999.0;  // Sentinel value indicating no calibration
  }

  // Single calibration point - use constant offset (not useful, but handle it)
  if (cal.count == 1) {
    return cal.points[0].dbm;
  }

  // Below lowest calibration point - extrapolate using first two points
  if (raw <= cal.points[0].raw) {
    return interpolate(raw, cal.points[0], cal.points[1]);
  }

  // Above highest calibration point - extrapolate using last two points
  if (raw >= cal.points[cal.count - 1].raw) {
    return interpolate(raw, cal.points[cal.count - 2], cal.points[cal.count - 1]);
  }

  // Find the two calibration points that bracket this raw value
  for (int i = 0; i < cal.count - 1; i++) {
    if (raw >= cal.points[i].raw && raw <= cal.points[i + 1].raw) {
      return interpolate(raw, cal.points[i], cal.points[i + 1]);
    }
  }

  // Should never reach here, but return midpoint if something goes wrong
  return cal.points[cal.count / 2].dbm;
}

// Read forward power in dBm
float read_fwd_dbm() {
  int raw = read_adc(fwd_adc_pin);
  return raw_to_dbm(fwd_cal, raw);
}

// Read reflected power in dBm
float read_ref_dbm() {
  int raw = read_adc(ref_adc_pin);
  return raw_to_dbm(ref_cal, raw);
}

// Convert dBm to watts
float dbm_to_watts(float dbm) {
  return pow(10.0, (dbm - 30.0) / 10.0);
}

// Convert watts to dBm
float watts_to_dbm(float watts) {
  if (watts <= 0.0) return -999.0;  // Invalid
  return 10.0 * log10(watts) + 30.0;
}

// Calculate SWR from forward and reflected power (in watts)
float calculate_swr(float fwd_watts, float ref_watts) {
  // Sanity checks
  if (fwd_watts <= 0.0) return 99.9;  // No forward power
  if (ref_watts < 0.0) ref_watts = 0.0;  // Negative reflected power is noise
  if (ref_watts >= fwd_watts) return 99.9;  // Reflected >= forward is invalid

  // Reflection coefficient: Γ = sqrt(P_ref / P_fwd)
  float gamma = sqrt(ref_watts / fwd_watts);

  // SWR = (1 + Γ) / (1 - Γ)
  if (gamma >= 1.0) return 99.9;  // Should not happen, but avoid divide by zero
  float swr = (1.0 + gamma) / (1.0 - gamma);

  // Clamp to reasonable range
  if (swr < 1.0) swr = 1.0;
  if (swr > 99.9) swr = 99.9;

  return swr;
}

// Add calibration point to table (inserts in sorted order by raw value)
bool add_cal_point(CalTable& cal, int raw, float dbm) {
  // Table full
  if (cal.count >= max_cal_points) {
    return false;
  }

  // Find insertion point (keep table sorted by raw value)
  int insert_index = cal.count;
  for (int i = 0; i < cal.count; i++) {
    if (raw < cal.points[i].raw) {
      insert_index = i;
      break;
    }
    // If raw value already exists, update it instead of inserting
    if (raw == cal.points[i].raw) {
      cal.points[i].dbm = dbm;
      return true;
    }
  }

  // Shift elements to make room
  for (int i = cal.count; i > insert_index; i--) {
    cal.points[i] = cal.points[i - 1];
  }

  // Insert new point
  cal.points[insert_index].raw = raw;
  cal.points[insert_index].dbm = dbm;
  cal.count++;

  return true;
}

// Save calibration to NVS (EEPROM)
void save_calibration() {
  preferences.begin("swr-cal", false);  // Read-write mode

  // Save forward calibration
  preferences.putInt("fwd_count", fwd_cal.count);
  for (int i = 0; i < fwd_cal.count; i++) {
    char key_raw[16], key_dbm[16];
    snprintf(key_raw, sizeof(key_raw), "fwd_raw_%d", i);
    snprintf(key_dbm, sizeof(key_dbm), "fwd_dbm_%d", i);
    preferences.putInt(key_raw, fwd_cal.points[i].raw);
    preferences.putFloat(key_dbm, fwd_cal.points[i].dbm);
  }

  // Save reflected calibration
  preferences.putInt("ref_count", ref_cal.count);
  for (int i = 0; i < ref_cal.count; i++) {
    char key_raw[16], key_dbm[16];
    snprintf(key_raw, sizeof(key_raw), "ref_raw_%d", i);
    snprintf(key_dbm, sizeof(key_dbm), "ref_dbm_%d", i);
    preferences.putInt(key_raw, ref_cal.points[i].raw);
    preferences.putFloat(key_dbm, ref_cal.points[i].dbm);
  }

  preferences.end();
  Serial.println("Calibration saved to NVS");
}

// Load calibration from NVS (EEPROM)
void load_calibration() {
  preferences.begin("swr-cal", true);  // Read-only mode

  // Load forward calibration
  fwd_cal.count = preferences.getInt("fwd_count", 0);
  if (fwd_cal.count > max_cal_points) fwd_cal.count = max_cal_points;
  for (int i = 0; i < fwd_cal.count; i++) {
    char key_raw[16], key_dbm[16];
    snprintf(key_raw, sizeof(key_raw), "fwd_raw_%d", i);
    snprintf(key_dbm, sizeof(key_dbm), "fwd_dbm_%d", i);
    fwd_cal.points[i].raw = preferences.getInt(key_raw, 0);
    fwd_cal.points[i].dbm = preferences.getFloat(key_dbm, 0.0);
  }

  // Load reflected calibration
  ref_cal.count = preferences.getInt("ref_count", 0);
  if (ref_cal.count > max_cal_points) ref_cal.count = max_cal_points;
  for (int i = 0; i < ref_cal.count; i++) {
    char key_raw[16], key_dbm[16];
    snprintf(key_raw, sizeof(key_raw), "ref_raw_%d", i);
    snprintf(key_dbm, sizeof(key_dbm), "ref_dbm_%d", i);
    ref_cal.points[i].raw = preferences.getInt(key_raw, 0);
    ref_cal.points[i].dbm = preferences.getFloat(key_dbm, 0.0);
  }

  preferences.end();
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
    send_response("N0GQ,ESP32-SCPI-SWR,1.0,2026\n");
  }

  // *RST - Reset (clear calibration tables - does not erase EEPROM)
  else if (strcmp(cmd, "*RST") == 0) {
    fwd_cal.count = 0;
    ref_cal.count = 0;
    power_unit = UNIT_DBM;
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // POW:FWD? - Query forward power
  else if (strcmp(cmd, "POW:FWD?") == 0 || strcmp(cmd, "POWER:FORWARD?") == 0) {
    float dbm = read_fwd_dbm();

    if (dbm == -999.0) {
      send_response("ERROR: No calibration data\n");
    } else {
      if (power_unit == UNIT_DBM) {
        snprintf(response, sizeof(response), "%.2f\n", dbm);
      } else {
        float watts = dbm_to_watts(dbm);
        snprintf(response, sizeof(response), "%.4f\n", watts);
      }
      send_response(response);
    }
  }

  // POW:REF? - Query reflected power
  else if (strcmp(cmd, "POW:REF?") == 0 || strcmp(cmd, "POWER:REFLECTED?") == 0) {
    float dbm = read_ref_dbm();

    if (dbm == -999.0) {
      send_response("ERROR: No calibration data\n");
    } else {
      if (power_unit == UNIT_DBM) {
        snprintf(response, sizeof(response), "%.2f\n", dbm);
      } else {
        float watts = dbm_to_watts(dbm);
        snprintf(response, sizeof(response), "%.4f\n", watts);
      }
      send_response(response);
    }
  }

  // SWR? - Query SWR
  else if (strcmp(cmd, "SWR?") == 0) {
    float fwd_dbm = read_fwd_dbm();
    float ref_dbm = read_ref_dbm();

    if (fwd_dbm == -999.0 || ref_dbm == -999.0) {
      send_response("ERROR: No calibration data\n");
    } else {
      float fwd_watts = dbm_to_watts(fwd_dbm);
      float ref_watts = dbm_to_watts(ref_dbm);
      float swr = calculate_swr(fwd_watts, ref_watts);
      snprintf(response, sizeof(response), "%.2f\n", swr);
      send_response(response);
    }
  }

  // POW:UNIT,<DBM|WATT> - Set power unit
  else if (strncmp(cmd, "POW:UNIT,", 9) == 0 || strncmp(cmd, "POWER:UNIT,", 11) == 0) {
    const char* unit_str = strchr(cmd, ',') + 1;

    if (strcmp(unit_str, "DBM") == 0) {
      power_unit = UNIT_DBM;
      send_response("OK\n");
    } else if (strcmp(unit_str, "WATT") == 0) {
      power_unit = UNIT_WATT;
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid unit (must be DBM or WATT)\n");
    }
  }

  // POW:UNIT? - Query power unit
  else if (strcmp(cmd, "POW:UNIT?") == 0 || strcmp(cmd, "POWER:UNIT?") == 0) {
    if (power_unit == UNIT_DBM) {
      send_response("DBM\n");
    } else {
      send_response("WATT\n");
    }
  }

  // CAL:FWD,<raw>,<dbm> - Add forward calibration point
  else if (strncmp(cmd, "CAL:FWD,", 8) == 0) {
    int raw;
    float dbm;
    if (sscanf(cmd + 8, "%d,%f", &raw, &dbm) == 2) {
      if (raw < 0 || raw > 4095) {
        send_response("ERROR: Raw value must be 0-4095\n");
      } else if (add_cal_point(fwd_cal, raw, dbm)) {
        snprintf(response, sizeof(response), "OK (FWD cal now has %d points)\n", fwd_cal.count);
        send_response(response);
      } else {
        send_response("ERROR: Calibration table full (max 16 points)\n");
      }
    } else {
      send_response("ERROR: Invalid parameters (need: raw,dbm)\n");
    }
  }

  // CAL:REF,<raw>,<dbm> - Add reflected calibration point
  else if (strncmp(cmd, "CAL:REF,", 8) == 0) {
    int raw;
    float dbm;
    if (sscanf(cmd + 8, "%d,%f", &raw, &dbm) == 2) {
      if (raw < 0 || raw > 4095) {
        send_response("ERROR: Raw value must be 0-4095\n");
      } else if (add_cal_point(ref_cal, raw, dbm)) {
        snprintf(response, sizeof(response), "OK (REF cal now has %d points)\n", ref_cal.count);
        send_response(response);
      } else {
        send_response("ERROR: Calibration table full (max 16 points)\n");
      }
    } else {
      send_response("ERROR: Invalid parameters (need: raw,dbm)\n");
    }
  }

  // CAL:SAV - Save calibration to EEPROM
  else if (strcmp(cmd, "CAL:SAV") == 0 || strcmp(cmd, "CAL:SAVE") == 0) {
    save_calibration();
    send_response("OK\n");
  }

  // CAL:LOAD - Load calibration from EEPROM
  else if (strcmp(cmd, "CAL:LOAD") == 0) {
    load_calibration();
    snprintf(response, sizeof(response), "OK (FWD %d points, REF %d points)\n",
             fwd_cal.count, ref_cal.count);
    send_response(response);
  }

  // CAL:FWD:CLEAR - Clear forward calibration table
  else if (strcmp(cmd, "CAL:FWD:CLEAR") == 0) {
    fwd_cal.count = 0;
    send_response("OK\n");
  }

  // CAL:REF:CLEAR - Clear reflected calibration table
  else if (strcmp(cmd, "CAL:REF:CLEAR") == 0) {
    ref_cal.count = 0;
    send_response("OK\n");
  }

  // CAL:FWD:COUNT? - Query number of forward calibration points
  else if (strcmp(cmd, "CAL:FWD:COUNT?") == 0) {
    snprintf(response, sizeof(response), "%d\n", fwd_cal.count);
    send_response(response);
  }

  // CAL:REF:COUNT? - Query number of reflected calibration points
  else if (strcmp(cmd, "CAL:REF:COUNT?") == 0) {
    snprintf(response, sizeof(response), "%d\n", ref_cal.count);
    send_response(response);
  }

  // ADC:FWD? - Query raw forward ADC value
  else if (strcmp(cmd, "ADC:FWD?") == 0) {
    int raw = read_adc(fwd_adc_pin);
    snprintf(response, sizeof(response), "%d\n", raw);
    send_response(response);
  }

  // ADC:REF? - Query raw reflected ADC value
  else if (strcmp(cmd, "ADC:REF?") == 0) {
    int raw = read_adc(ref_adc_pin);
    snprintf(response, sizeof(response), "%d\n", raw);
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
