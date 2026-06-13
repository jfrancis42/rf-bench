/*
 * SCPI NeoPixel (WS2812B) Controller for ESP32
 *
 * Controls addressable LED strips via SCPI commands over TCP/IP
 * Compatible with WS2812B, WS2811, SK6812, and similar LEDs
 *
 * Hardware connections:
 *   LED strip:
 *     GPIO 25 -> Data In (DIN)
 *     5V PSU -> LED strip VCC (1A per 60 LEDs at full white)
 *     GND -> LED strip GND + ESP32 GND (common ground required)
 *
 * Note: WS2812B strips are 5V logic but ESP32 GPIO (3.3V) often works
 * due to generous HIGH threshold (~3.5V typical). For reliability, add
 * a 74HCT125 level shifter or 330Ω resistor near the strip's data input.
 *
 * Power: LED strips draw significant current (60mA per LED at full white).
 * DO NOT power from ESP32 — use external 5V PSU rated for 1A per 60 LEDs.
 * Example: 60-LED strip at full white = 3.6A, use 5A PSU minimum.
 *
 * Library: Adafruit_NeoPixel (install via Arduino Library Manager)
 */

#include <WiFi.h>
#include <Adafruit_NeoPixel.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// LED strip configuration
const int led_pin = 25;              // Data GPIO
const int max_leds = 300;            // Safety limit for strip length
int num_leds = 60;                   // Default strip length (configurable via SCPI)
uint8_t brightness = 255;            // Global brightness (0-255, default full)

// NeoPixel object (dynamically resizable via NEO:LEN command)
Adafruit_NeoPixel strip(num_leds, led_pin, NEO_GRB + NEO_KHZ800);

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI NeoPixel Controller");
  Serial.println("========================");

  // Initialize LED strip
  strip.begin();
  strip.clear();
  strip.setBrightness(brightness);
  strip.show();  // Initialize all pixels to 'off'

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
  Serial.printf("LED strip: %d pixels on GPIO %d\n", num_leds, led_pin);
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
    send_response("N0GQ,ESP32-SCPI-NeoPixel,1.0,2026\n");
  }

  // *RST - Reset (clear all pixels)
  else if (strcmp(cmd, "*RST") == 0) {
    strip.clear();
    strip.show();
    send_response("OK\n");
  }

  // SYST:ERR? - System error (always none for this simple device)
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // NEO:LEN,<n> - Set strip length
  else if (strncmp(cmd, "NEO:LEN", 7) == 0 && strchr(cmd, ',')) {
    int new_len = 0;
    sscanf(strchr(cmd, ','), ",%d", &new_len);

    if (new_len > 0 && new_len <= max_leds) {
      num_leds = new_len;
      strip.updateLength(num_leds);
      strip.clear();
      strip.show();
      send_response("OK\n");
    } else {
      send_response("ERROR: Length must be 1-300\n");
    }
  }

  // NEO:LEN? - Query strip length
  else if (strcmp(cmd, "NEO:LEN?") == 0) {
    char response[16];
    snprintf(response, sizeof(response), "%d\n", num_leds);
    send_response(response);
  }

  // NEO:PIX (@n),<r>,<g>,<b> - Set single pixel
  else if (strncmp(cmd, "NEO:PIX", 7) == 0) {
    int pixel = parse_pixel_number(cmd);
    int r, g, b;

    if (pixel >= 0 && pixel < num_leds && sscanf(cmd, "NEO:PIX (@%*d),%d,%d,%d", &r, &g, &b) == 3) {
      if (r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255) {
        strip.setPixelColor(pixel, strip.Color(r, g, b));
        send_response("OK\n");
      } else {
        send_response("ERROR: RGB values must be 0-255\n");
      }
    } else {
      send_response("ERROR: Invalid pixel number or RGB format\n");
    }
  }

  // NEO:ALL,<r>,<g>,<b> - Set all pixels
  else if (strncmp(cmd, "NEO:ALL", 7) == 0 && strchr(cmd, ',')) {
    int r, g, b;

    if (sscanf(cmd, "NEO:ALL,%d,%d,%d", &r, &g, &b) == 3) {
      if (r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255) {
        for (int i = 0; i < num_leds; i++) {
          strip.setPixelColor(i, strip.Color(r, g, b));
        }
        send_response("OK\n");
      } else {
        send_response("ERROR: RGB values must be 0-255\n");
      }
    } else {
      send_response("ERROR: Invalid RGB format\n");
    }
  }

  // NEO:FILL,<start>,<count>,<r>,<g>,<b> - Fill range
  else if (strncmp(cmd, "NEO:FILL", 8) == 0 && strchr(cmd, ',')) {
    int start, count, r, g, b;

    if (sscanf(cmd, "NEO:FILL,%d,%d,%d,%d,%d", &start, &count, &r, &g, &b) == 5) {
      if (start >= 0 && start < num_leds && count > 0 &&
          start + count <= num_leds &&
          r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255) {
        strip.fill(strip.Color(r, g, b), start, count);
        send_response("OK\n");
      } else {
        send_response("ERROR: Invalid range or RGB values\n");
      }
    } else {
      send_response("ERROR: Invalid format (expected: start,count,r,g,b)\n");
    }
  }

  // NEO:BRI,<0-100> - Set brightness (percent)
  else if (strncmp(cmd, "NEO:BRI", 7) == 0 && strchr(cmd, ',')) {
    int percent = 0;
    sscanf(strchr(cmd, ','), ",%d", &percent);

    if (percent >= 0 && percent <= 100) {
      brightness = (uint8_t)((percent * 255) / 100);
      strip.setBrightness(brightness);
      send_response("OK\n");
    } else {
      send_response("ERROR: Brightness must be 0-100 percent\n");
    }
  }

  // NEO:BRI? - Query brightness
  else if (strcmp(cmd, "NEO:BRI?") == 0) {
    int percent = (brightness * 100) / 255;
    char response[16];
    snprintf(response, sizeof(response), "%d\n", percent);
    send_response(response);
  }

  // NEO:SHOW - Update strip (latch)
  else if (strcmp(cmd, "NEO:SHOW") == 0) {
    strip.show();
    send_response("OK\n");
  }

  // NEO:CLEA - Clear all pixels to off
  else if (strcmp(cmd, "NEO:CLEA") == 0 || strcmp(cmd, "NEO:CLEAR") == 0) {
    strip.clear();
    send_response("OK\n");
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}

// Parse pixel number from SCPI command (e.g., "NEO:PIX (@5),...")
int parse_pixel_number(const char* cmd) {
  const char* at_sign = strchr(cmd, '@');
  if (!at_sign) return -1;

  int pixel = -1;
  sscanf(at_sign, "@%d", &pixel);

  return pixel;  // Already 0-indexed (unlike relay which subtracts 1)
}
