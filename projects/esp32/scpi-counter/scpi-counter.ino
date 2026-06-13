/*
 * SCPI Frequency Counter for ESP32
 *
 * Frequency and event counter using ESP32 PCNT (pulse counter) peripheral
 * Provides SCPI commands over TCP/IP for automated test equipment integration
 *
 * Hardware connections:
 *   Signal input:
 *     GPIO 4 -> Pulse input (3.3V logic, max ~40 MHz)
 *
 * PCNT peripheral features:
 *   - Hardware pulse counting (no CPU involvement)
 *   - 16-bit signed counter (-32768 to +32767)
 *   - Overflow/underflow handling via interrupts
 *   - Edge detection on rising or falling edges
 *
 * Operating modes:
 *   FREQ: Frequency measurement (Hz) — counts pulses over gate time
 *   EVENT: Event counter — total accumulated count, manually reset
 *
 * SCPI commands:
 *   COUN:FREQ? — measure frequency (returns Hz)
 *   COUN:EVEN? — read event count (returns total count)
 *   COUN:RES — reset event counter to zero
 *   COUN:GATE,<ms> — set gate time in milliseconds (default 1000)
 *   COUN:GATE? — query gate time
 *   COUN:MODE,<FREQ|EVENT> — set mode
 *   COUN:MODE? — query mode
 */

#include <WiFi.h>
#include "driver/pcnt.h"

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// Pulse input GPIO
const int pulse_input_pin = 4;

// PCNT unit
const pcnt_unit_t pcnt_unit = PCNT_UNIT_0;

// Gate time for frequency measurement (milliseconds)
volatile uint32_t gate_time_ms = 1000;

// Operating mode
enum CounterMode {
  MODE_FREQ,    // Frequency measurement
  MODE_EVENT    // Event counter
};
volatile CounterMode counter_mode = MODE_FREQ;

// Event counter overflow tracking
volatile int32_t overflow_count = 0;  // Tracks 16-bit PCNT overflows
volatile int64_t total_count = 0;     // Accumulated event count

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

// PCNT interrupt handler for overflow/underflow
void IRAM_ATTR pcnt_overflow_handler(void *arg) {
  uint32_t status = 0;
  pcnt_get_event_status(pcnt_unit, &status);

  if (status & PCNT_EVT_H_LIM) {
    // Overflow: counter reached +32767
    overflow_count++;
  }
  if (status & PCNT_EVT_L_LIM) {
    // Underflow: counter reached -32768
    overflow_count--;
  }
}

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Frequency Counter");
  Serial.println("======================");

  // Initialize PCNT
  init_pcnt();

  Serial.printf("Pulse input: GPIO %d\n", pulse_input_pin);
  Serial.printf("Default gate time: %u ms\n", gate_time_ms);

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

// Initialize PCNT peripheral
void init_pcnt() {
  // PCNT configuration
  pcnt_config_t pcnt_config = {
    .pulse_gpio_num = pulse_input_pin,
    .ctrl_gpio_num = PCNT_PIN_NOT_USED,
    .lctrl_mode = PCNT_MODE_KEEP,
    .hctrl_mode = PCNT_MODE_KEEP,
    .pos_mode = PCNT_COUNT_INC,    // Count on rising edge
    .neg_mode = PCNT_COUNT_DIS,    // Don't count on falling edge
    .counter_h_lim = 32767,        // Upper limit
    .counter_l_lim = -32768,       // Lower limit
    .unit = pcnt_unit,
    .channel = PCNT_CHANNEL_0,
  };

  // Initialize PCNT
  pcnt_unit_config(&pcnt_config);

  // Set filter (ignore glitches < ~1 µs at 80 MHz APB clock)
  // Filter value = 1023 APB cycles ~ 13 µs @ 80 MHz
  pcnt_set_filter_value(pcnt_unit, 1023);
  pcnt_filter_enable(pcnt_unit);

  // Enable events for overflow/underflow
  pcnt_event_enable(pcnt_unit, PCNT_EVT_H_LIM);
  pcnt_event_enable(pcnt_unit, PCNT_EVT_L_LIM);

  // Register ISR handler
  pcnt_isr_service_install(0);
  pcnt_isr_handler_add(pcnt_unit, pcnt_overflow_handler, NULL);

  // Clear counter
  pcnt_counter_pause(pcnt_unit);
  pcnt_counter_clear(pcnt_unit);
  overflow_count = 0;
  total_count = 0;
  pcnt_counter_resume(pcnt_unit);

  Serial.println("PCNT initialized");
}

// Measure frequency (Hz)
float measure_frequency() {
  // Clear counter
  pcnt_counter_pause(pcnt_unit);
  pcnt_counter_clear(pcnt_unit);
  overflow_count = 0;

  // Start counting
  pcnt_counter_resume(pcnt_unit);

  // Wait for gate time
  delay(gate_time_ms);

  // Stop and read counter
  pcnt_counter_pause(pcnt_unit);
  int16_t count_raw;
  pcnt_get_counter_value(pcnt_unit, &count_raw);

  // Total count including overflows
  int64_t total = (int64_t)overflow_count * 65536LL + (int64_t)count_raw;

  // Resume counting (for continuous operation)
  pcnt_counter_resume(pcnt_unit);

  // Calculate frequency (Hz)
  float frequency = (float)total * 1000.0f / (float)gate_time_ms;

  return frequency;
}

// Read event counter
int64_t read_event_count() {
  // Read current counter value
  int16_t count_raw;
  pcnt_get_counter_value(pcnt_unit, &count_raw);

  // Total count including overflows
  total_count = (int64_t)overflow_count * 65536LL + (int64_t)count_raw;

  return total_count;
}

// Reset event counter
void reset_event_counter() {
  pcnt_counter_pause(pcnt_unit);
  pcnt_counter_clear(pcnt_unit);
  overflow_count = 0;
  total_count = 0;
  pcnt_counter_resume(pcnt_unit);
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
    send_response("N0GQ,ESP32-SCPI-Counter,1.0,2026\n");
  }

  // *RST - Reset (clear event counter, set defaults)
  else if (strcmp(cmd, "*RST") == 0) {
    reset_event_counter();
    gate_time_ms = 1000;
    counter_mode = MODE_FREQ;
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // COUN:FREQ? - Measure frequency
  else if (strcmp(cmd, "COUN:FREQ?") == 0 || strcmp(cmd, "COUNT:FREQ?") == 0 ||
           strcmp(cmd, "COUNTER:FREQUENCY?") == 0) {
    float freq = measure_frequency();
    snprintf(response, sizeof(response), "%.3f\n", freq);
    send_response(response);
  }

  // COUN:EVEN? - Read event count
  else if (strcmp(cmd, "COUN:EVEN?") == 0 || strcmp(cmd, "COUNT:EVEN?") == 0 ||
           strcmp(cmd, "COUNTER:EVENT?") == 0) {
    int64_t count = read_event_count();
    snprintf(response, sizeof(response), "%lld\n", count);
    send_response(response);
  }

  // COUN:RES - Reset event counter
  else if (strcmp(cmd, "COUN:RES") == 0 || strcmp(cmd, "COUNT:RES") == 0 ||
           strcmp(cmd, "COUNTER:RESET") == 0) {
    reset_event_counter();
    send_response("OK\n");
  }

  // COUN:GATE,<ms> - Set gate time
  else if (strncmp(cmd, "COUN:GATE", 9) == 0 || strncmp(cmd, "COUNT:GATE", 10) == 0 ||
           strncmp(cmd, "COUNTER:GATE", 12) == 0) {
    // Find comma
    char* comma = strchr(cmd, ',');
    if (comma) {
      uint32_t new_gate = atoi(comma + 1);
      if (new_gate >= 10 && new_gate <= 60000) {  // 10ms to 60s
        gate_time_ms = new_gate;
        send_response("OK\n");
      } else {
        send_response("ERROR: Gate time must be 10-60000 ms\n");
      }
    } else {
      send_response("ERROR: Missing gate time parameter\n");
    }
  }

  // COUN:GATE? - Query gate time
  else if (strcmp(cmd, "COUN:GATE?") == 0 || strcmp(cmd, "COUNT:GATE?") == 0 ||
           strcmp(cmd, "COUNTER:GATE?") == 0) {
    snprintf(response, sizeof(response), "%u\n", gate_time_ms);
    send_response(response);
  }

  // COUN:MODE,<FREQ|EVENT> - Set mode
  else if (strncmp(cmd, "COUN:MODE", 9) == 0 || strncmp(cmd, "COUNT:MODE", 10) == 0 ||
           strncmp(cmd, "COUNTER:MODE", 12) == 0) {
    // Find comma
    char* comma = strchr(cmd, ',');
    if (comma) {
      char* mode_str = comma + 1;
      // Trim leading whitespace
      while (*mode_str == ' ' || *mode_str == '\t') mode_str++;

      if (strcmp(mode_str, "FREQ") == 0 || strcmp(mode_str, "FREQUENCY") == 0) {
        counter_mode = MODE_FREQ;
        send_response("OK\n");
      } else if (strcmp(mode_str, "EVEN") == 0 || strcmp(mode_str, "EVENT") == 0) {
        counter_mode = MODE_EVENT;
        reset_event_counter();  // Reset on mode change
        send_response("OK\n");
      } else {
        send_response("ERROR: Mode must be FREQ or EVENT\n");
      }
    } else {
      send_response("ERROR: Missing mode parameter\n");
    }
  }

  // COUN:MODE? - Query mode
  else if (strcmp(cmd, "COUN:MODE?") == 0 || strcmp(cmd, "COUNT:MODE?") == 0 ||
           strcmp(cmd, "COUNTER:MODE?") == 0) {
    send_response(counter_mode == MODE_FREQ ? "FREQ\n" : "EVENT\n");
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
