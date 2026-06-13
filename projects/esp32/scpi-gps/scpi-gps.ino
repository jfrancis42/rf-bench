/*
 * SCPI GPS Controller for ESP32
 *
 * Reads NMEA data from serial GPS module and provides SCPI access over TCP/IP
 * Compatible with typical cheap Amazon/AliExpress GPS modules (NEO-6M, NEO-7M, etc.)
 *
 * Hardware connections:
 *   GPS Module -> ESP32
 *     VCC -> 3.3V or 5V (check module spec)
 *     GND -> GND
 *     TX  -> GPIO 16 (RX2)
 *     RX  -> GPIO 17 (TX2) [optional, not used for read-only]
 *
 * GPS modules typically output NMEA sentences at 9600 baud (some at 4800 or 38400)
 * Most common sentences: $GPGGA, $GPRMC, $GPGSA, $GPGSV, $GPVTG, $GPGLL
 *
 * SCPI provides parsed GPS data (lat, lon, altitude, speed, heading, etc.)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// GPS serial port (using UART2)
HardwareSerial GPSSerial(2);
const int gps_rx_pin = 16;  // ESP32 RX2 <- GPS TX
const int gps_tx_pin = 17;  // ESP32 TX2 -> GPS RX (not used)
const long gps_baud = 9600; // Most GPS modules use 9600 (try 4800 or 38400 if no data)

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// NMEA sentence buffer
char nmea_buffer[128];
int nmea_index = 0;

// GPS data structure
struct {
  bool valid;               // Fix valid
  unsigned long last_update; // millis() of last valid parse

  // Position
  double latitude;          // Decimal degrees (+ = N, - = S)
  double longitude;         // Decimal degrees (+ = E, - = W)
  float altitude;           // Meters above MSL

  // Time
  int hour;                 // UTC hours (0-23)
  int minute;               // UTC minutes (0-59)
  int second;               // UTC seconds (0-59)

  // Date (from RMC)
  int day;
  int month;
  int year;

  // Motion
  float speed_knots;        // Speed over ground (knots)
  float speed_kmh;          // Speed over ground (km/h)
  float track_deg;          // Course over ground (degrees true)

  // Quality
  int fix_quality;          // 0=invalid, 1=GPS, 2=DGPS
  int satellites;           // Number of satellites in use
  float hdop;               // Horizontal dilution of precision

  // Magnetic variation (from RMC)
  float mag_var;            // Magnetic variation (degrees)
  char mag_var_dir;         // 'E' or 'W'

} gps_data;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI GPS Controller");
  Serial.println("===================");

  // Initialize GPS data
  memset(&gps_data, 0, sizeof(gps_data));
  gps_data.valid = false;

  // Start GPS serial port
  GPSSerial.begin(gps_baud, SERIAL_8N1, gps_rx_pin, gps_tx_pin);
  Serial.printf("GPS serial: %d baud on RX=%d, TX=%d\n", gps_baud, gps_rx_pin, gps_tx_pin);

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
  Serial.println("Waiting for GPS fix...");

  // Start SCPI server
  server.begin();
}

void loop() {
  // Read and parse GPS data
  read_gps();

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

// Read GPS data from serial port
void read_gps() {
  while (GPSSerial.available()) {
    char c = GPSSerial.read();

    // Start of NMEA sentence
    if (c == '$') {
      nmea_index = 0;
      nmea_buffer[nmea_index++] = c;
    }
    // End of NMEA sentence
    else if (c == '\n' || c == '\r') {
      if (nmea_index > 0) {
        nmea_buffer[nmea_index] = '\0';
        parse_nmea(nmea_buffer);
        nmea_index = 0;
      }
    }
    // Add character to buffer
    else if (nmea_index < sizeof(nmea_buffer) - 1) {
      nmea_buffer[nmea_index++] = c;
    }
    // Buffer overflow - reset
    else {
      nmea_index = 0;
    }
  }
}

// Parse NMEA sentence
void parse_nmea(const char* sentence) {
  // Verify checksum
  if (!verify_checksum(sentence)) {
    return;
  }

  // Parse based on sentence type
  if (strncmp(sentence, "$GPGGA", 6) == 0 || strncmp(sentence, "$GNGGA", 6) == 0) {
    parse_gga(sentence);
  }
  else if (strncmp(sentence, "$GPRMC", 6) == 0 || strncmp(sentence, "$GNRMC", 6) == 0) {
    parse_rmc(sentence);
  }
  else if (strncmp(sentence, "$GPVTG", 6) == 0 || strncmp(sentence, "$GNVTG", 6) == 0) {
    parse_vtg(sentence);
  }
}

// Verify NMEA checksum
bool verify_checksum(const char* sentence) {
  // Find the asterisk
  const char* asterisk = strchr(sentence, '*');
  if (!asterisk) return false;

  // Calculate checksum (XOR of all characters between $ and *)
  uint8_t checksum = 0;
  for (const char* p = sentence + 1; p < asterisk; p++) {
    checksum ^= *p;
  }

  // Parse provided checksum
  uint8_t provided_checksum = 0;
  sscanf(asterisk + 1, "%2hhx", &provided_checksum);

  return checksum == provided_checksum;
}

// Parse $GPGGA sentence (position, altitude, fix quality)
void parse_gga(const char* sentence) {
  char time_str[16], lat_str[16], lat_dir, lon_str[16], lon_dir;
  int fix_quality, num_sats;
  float hdop, altitude, geoid_sep;

  int parsed = sscanf(sentence, "$G%*cGGA,%[^,],%[^,],%c,%[^,],%c,%d,%d,%f,%f,M,%f",
                      time_str, lat_str, &lat_dir, lon_str, &lon_dir,
                      &fix_quality, &num_sats, &hdop, &altitude, &geoid_sep);

  if (parsed >= 9) {
    // Parse time (hhmmss.sss)
    float time_float;
    sscanf(time_str, "%f", &time_float);
    int time_int = (int)time_float;
    gps_data.hour = time_int / 10000;
    gps_data.minute = (time_int / 100) % 100;
    gps_data.second = time_int % 100;

    // Parse latitude (ddmm.mmmm)
    float lat_raw;
    sscanf(lat_str, "%f", &lat_raw);
    int lat_deg = (int)(lat_raw / 100);
    float lat_min = lat_raw - (lat_deg * 100);
    gps_data.latitude = lat_deg + (lat_min / 60.0);
    if (lat_dir == 'S') gps_data.latitude = -gps_data.latitude;

    // Parse longitude (dddmm.mmmm)
    float lon_raw;
    sscanf(lon_str, "%f", &lon_raw);
    int lon_deg = (int)(lon_raw / 100);
    float lon_min = lon_raw - (lon_deg * 100);
    gps_data.longitude = lon_deg + (lon_min / 60.0);
    if (lon_dir == 'W') gps_data.longitude = -gps_data.longitude;

    gps_data.fix_quality = fix_quality;
    gps_data.satellites = num_sats;
    gps_data.hdop = hdop;
    gps_data.altitude = altitude;

    if (fix_quality > 0) {
      gps_data.valid = true;
      gps_data.last_update = millis();
    }
  }
}

// Parse $GPRMC sentence (position, date, speed, course)
void parse_rmc(const char* sentence) {
  char status, time_str[16], lat_str[16], lat_dir, lon_str[16], lon_dir;
  char date_str[16], mag_var_str[16], mag_var_dir;
  float speed_knots, track_deg;

  int parsed = sscanf(sentence, "$G%*cRMC,%[^,],%c,%[^,],%c,%[^,],%c,%f,%f,%[^,],%[^,],%c",
                      time_str, &status, lat_str, &lat_dir, lon_str, &lon_dir,
                      &speed_knots, &track_deg, date_str, mag_var_str, &mag_var_dir);

  if (parsed >= 9 && status == 'A') {  // A = Active/valid
    // Parse date (ddmmyy)
    int date_int;
    sscanf(date_str, "%d", &date_int);
    gps_data.day = date_int / 10000;
    gps_data.month = (date_int / 100) % 100;
    gps_data.year = 2000 + (date_int % 100);

    gps_data.speed_knots = speed_knots;
    gps_data.speed_kmh = speed_knots * 1.852;
    gps_data.track_deg = track_deg;

    if (parsed >= 11) {
      sscanf(mag_var_str, "%f", &gps_data.mag_var);
      gps_data.mag_var_dir = mag_var_dir;
    }
  }
}

// Parse $GPVTG sentence (course and speed)
void parse_vtg(const char* sentence) {
  float track_true, track_mag, speed_knots, speed_kmh;

  int parsed = sscanf(sentence, "$G%*cVTG,%f,T,%f,M,%f,N,%f,K",
                      &track_true, &track_mag, &speed_knots, &speed_kmh);

  if (parsed >= 4) {
    gps_data.track_deg = track_true;
    gps_data.speed_knots = speed_knots;
    gps_data.speed_kmh = speed_kmh;
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
    send_response("N0GQ,ESP32-SCPI-GPS,1.0,2026\n");
  }

  // *RST - Reset (clear GPS data)
  else if (strcmp(cmd, "*RST") == 0) {
    memset(&gps_data, 0, sizeof(gps_data));
    gps_data.valid = false;
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // GPS:FIX? - Query fix status
  else if (strcmp(cmd, "GPS:FIX?") == 0) {
    snprintf(response, sizeof(response), "%d\n", gps_data.valid ? 1 : 0);
    send_response(response);
  }

  // GPS:LAT? - Query latitude
  else if (strcmp(cmd, "GPS:LAT?") == 0 || strcmp(cmd, "GPS:LATITUDE?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.8f\n", gps_data.latitude);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:LON? - Query longitude
  else if (strcmp(cmd, "GPS:LON?") == 0 || strcmp(cmd, "GPS:LONGITUDE?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.8f\n", gps_data.longitude);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:ALT? - Query altitude
  else if (strcmp(cmd, "GPS:ALT?") == 0 || strcmp(cmd, "GPS:ALTITUDE?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", gps_data.altitude);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:SPEED? - Query speed (km/h by default)
  else if (strcmp(cmd, "GPS:SPEED?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", gps_data.speed_kmh);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:SPEED:KNOTS? - Query speed in knots
  else if (strcmp(cmd, "GPS:SPEED:KNOTS?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", gps_data.speed_knots);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:TRACK? - Query course/heading
  else if (strcmp(cmd, "GPS:TRACK?") == 0 || strcmp(cmd, "GPS:HEADING?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", gps_data.track_deg);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:TIME? - Query UTC time (HH:MM:SS)
  else if (strcmp(cmd, "GPS:TIME?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%02d:%02d:%02d\n",
               gps_data.hour, gps_data.minute, gps_data.second);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:DATE? - Query date (YYYY-MM-DD)
  else if (strcmp(cmd, "GPS:DATE?") == 0) {
    if (gps_data.valid && gps_data.year > 0) {
      snprintf(response, sizeof(response), "%04d-%02d-%02d\n",
               gps_data.year, gps_data.month, gps_data.day);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix or date\n");
    }
  }

  // GPS:SATS? - Query satellite count
  else if (strcmp(cmd, "GPS:SATS?") == 0 || strcmp(cmd, "GPS:SATELLITES?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%d\n", gps_data.satellites);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:HDOP? - Query HDOP
  else if (strcmp(cmd, "GPS:HDOP?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%.2f\n", gps_data.hdop);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:QUAL? - Query fix quality
  else if (strcmp(cmd, "GPS:QUAL?") == 0 || strcmp(cmd, "GPS:QUALITY?") == 0) {
    if (gps_data.valid) {
      snprintf(response, sizeof(response), "%d\n", gps_data.fix_quality);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:ALL? - Query all data as CSV
  else if (strcmp(cmd, "GPS:ALL?") == 0) {
    if (gps_data.valid) {
      // Format: lat,lon,alt,speed_kmh,track,hour,min,sec,year,month,day,sats,hdop,fix_qual
      snprintf(response, sizeof(response),
               "%.8f,%.8f,%.2f,%.2f,%.2f,%02d,%02d,%02d,%04d,%02d,%02d,%d,%.2f,%d\n",
               gps_data.latitude, gps_data.longitude, gps_data.altitude,
               gps_data.speed_kmh, gps_data.track_deg,
               gps_data.hour, gps_data.minute, gps_data.second,
               gps_data.year, gps_data.month, gps_data.day,
               gps_data.satellites, gps_data.hdop, gps_data.fix_quality);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // GPS:AGE? - Query age of last fix (milliseconds)
  else if (strcmp(cmd, "GPS:AGE?") == 0) {
    if (gps_data.valid) {
      unsigned long age = millis() - gps_data.last_update;
      snprintf(response, sizeof(response), "%lu\n", age);
      send_response(response);
    } else {
      send_response("ERROR: No GPS fix\n");
    }
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
