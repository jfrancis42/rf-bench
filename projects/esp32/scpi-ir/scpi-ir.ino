/*
 * SCPI Infrared TX/RX Controller for ESP32
 *
 * Infrared transceiver with SCPI control over TCP/IP
 * Supports NEC, RC5, Sony, and raw IR protocols
 * Compatible with typical IR LEDs and TSOP38238 receivers
 *
 * Hardware connections:
 *   IR LED (TX):
 *     GPIO 25 -> IR LED anode (via 100-220Ω resistor)
 *     GND -> IR LED cathode
 *
 *   TSOP38238 IR Receiver (RX):
 *     GPIO 26 -> TSOP38238 OUT pin
 *     3.3V -> TSOP38238 VCC pin
 *     GND -> TSOP38238 GND pin
 *
 * IR protocols supported:
 *   - NEC (32-bit, most common for TV/AC remotes)
 *   - RC5 (Philips, 13-bit)
 *   - Sony SIRC (12/15/20-bit)
 *   - RAW (arbitrary mark/space timings)
 *
 * Default carrier frequency: 38 kHz (configurable 36/38/40 kHz)
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// GPIO pins
const int ir_tx_pin = 25;  // PWM output for IR LED carrier
const int ir_rx_pin = 26;  // Input from TSOP38238

// IR carrier settings
volatile uint32_t carrier_freq_hz = 38000;  // Default 38 kHz
volatile uint32_t carrier_period_us;
volatile bool carrier_enabled = false;

// PWM settings for ESP32
const int pwm_channel = 0;
const int pwm_resolution = 8;  // 8-bit resolution (0-255)
const int pwm_duty = 128;      // 50% duty cycle

// RX buffer for decoded frames
#define MAX_RX_FRAMES 16
struct IRFrame {
  uint8_t protocol;  // 0=NEC, 1=RC5, 2=Sony, 3=Raw
  uint32_t address;
  uint32_t command;
  uint16_t raw_count;
  uint16_t raw_data[256];  // Mark/space timings in microseconds
  unsigned long timestamp;
};

volatile IRFrame rx_buffer[MAX_RX_FRAMES];
volatile uint8_t rx_write_idx = 0;
volatile uint8_t rx_read_idx = 0;

// RX state machine
volatile uint32_t last_edge_us = 0;
volatile uint16_t edge_buffer[512];
volatile uint16_t edge_count = 0;
volatile bool frame_ready = false;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[512];
int cmd_index = 0;

void IRAM_ATTR ir_rx_isr();
void decode_frame();
void send_nec(uint16_t addr, uint8_t cmd);
void send_rc5(uint8_t addr, uint8_t cmd, bool toggle);
void send_sony(uint16_t addr, uint8_t cmd, uint8_t bits);
void send_raw(uint32_t freq, const uint16_t* timings, uint16_t count);
void mark(uint16_t us);
void space(uint16_t us);
void enable_carrier(uint32_t freq_hz);
void disable_carrier();

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI Infrared TX/RX Controller");
  Serial.println("==============================");

  // Initialize carrier frequency calculation
  carrier_period_us = 1000000UL / carrier_freq_hz;

  // Initialize TX pin (PWM for carrier generation)
  ledcSetup(pwm_channel, carrier_freq_hz, pwm_resolution);
  ledcAttachPin(ir_tx_pin, pwm_channel);
  ledcWrite(pwm_channel, 0);  // Off initially
  Serial.printf("IR TX: GPIO %d (PWM carrier)\n", ir_tx_pin);

  // Initialize RX pin with interrupt
  pinMode(ir_rx_pin, INPUT);
  attachInterrupt(digitalPinToInterrupt(ir_rx_pin), ir_rx_isr, CHANGE);
  Serial.printf("IR RX: GPIO %d (TSOP38238)\n", ir_rx_pin);

  // Initialize RX buffer
  memset((void*)rx_buffer, 0, sizeof(rx_buffer));

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
  Serial.printf("Carrier frequency: %d kHz\n", carrier_freq_hz / 1000);
  Serial.println("\nReady for SCPI commands");

  // Start SCPI server
  server.begin();
}

void loop() {
  // Check for completed IR frames
  if (frame_ready) {
    noInterrupts();
    frame_ready = false;
    uint16_t edges = edge_count;
    uint16_t temp_edges[512];
    memcpy(temp_edges, (void*)edge_buffer, edges * sizeof(uint16_t));
    edge_count = 0;
    interrupts();

    decode_frame(temp_edges, edges);
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
        Serial.println("Command buffer overflow!");
        cmd_index = 0;
        memset(cmd_buffer, 0, sizeof(cmd_buffer));
        send_response("ERROR: Command too long\n");
      }
    }
  }
}

// IR RX interrupt handler
void IRAM_ATTR ir_rx_isr() {
  uint32_t now_us = micros();
  uint32_t duration = now_us - last_edge_us;
  last_edge_us = now_us;

  // Ignore glitches < 50us or > 50ms
  if (duration < 50 || duration > 50000) {
    return;
  }

  // Store edge timing
  if (edge_count < 512) {
    edge_buffer[edge_count++] = duration;
  }

  // End of frame: no edge for > 10ms
  if (duration > 10000 && edge_count > 10) {
    frame_ready = true;
  }
}

// Decode captured IR frame
void decode_frame(const uint16_t* edges, uint16_t count) {
  if (count < 10) return;  // Too short

  // Try NEC decode (9ms mark, 4.5ms space header)
  if (edges[0] > 8000 && edges[0] < 10000 &&
      edges[1] > 4000 && edges[1] < 5000) {
    uint32_t code = 0;
    bool valid = true;

    for (int i = 0; i < 32; i++) {
      int mark_idx = 2 + i * 2;
      int space_idx = mark_idx + 1;

      if (space_idx >= count) {
        valid = false;
        break;
      }

      // NEC: 560us mark, then 560us space (0) or 1680us space (1)
      if (edges[space_idx] > 1200) {
        code |= (1UL << i);
      }
    }

    if (valid) {
      uint8_t addr = (code >> 24) & 0xFF;
      uint8_t cmd = (code >> 8) & 0xFF;

      volatile IRFrame* frame = &rx_buffer[rx_write_idx];
      frame->protocol = 0;  // NEC
      frame->address = addr;
      frame->command = cmd;
      frame->raw_count = 0;
      frame->timestamp = millis();

      rx_write_idx = (rx_write_idx + 1) % MAX_RX_FRAMES;
      Serial.printf("RX NEC: addr=0x%02X cmd=0x%02X\n", addr, cmd);
      return;
    }
  }

  // Try RC5 decode (889us half-bit periods, 1778us full bits)
  // RC5 starts with 2 start bits (always 1), then toggle, then 5-bit addr, 6-bit cmd
  // Simplified decode: look for ~900us or ~1800us periods
  bool might_be_rc5 = true;
  for (int i = 0; i < min(count, 28); i++) {
    if (edges[i] < 600 || edges[i] > 2200) {
      might_be_rc5 = false;
      break;
    }
  }

  if (might_be_rc5 && count >= 24) {
    // RC5 decode logic here (complex, simplified for now)
    // Store as raw for now
    volatile IRFrame* frame = &rx_buffer[rx_write_idx];
    frame->protocol = 3;  // Raw
    frame->raw_count = min(count, 256);
    memcpy((void*)frame->raw_data, edges, frame->raw_count * sizeof(uint16_t));
    frame->timestamp = millis();
    rx_write_idx = (rx_write_idx + 1) % MAX_RX_FRAMES;
    Serial.printf("RX RC5/Unknown: %d edges\n", count);
    return;
  }

  // Default: store as raw
  volatile IRFrame* frame = &rx_buffer[rx_write_idx];
  frame->protocol = 3;  // Raw
  frame->raw_count = min(count, 256);
  memcpy((void*)frame->raw_data, edges, frame->raw_count * sizeof(uint16_t));
  frame->timestamp = millis();
  rx_write_idx = (rx_write_idx + 1) % MAX_RX_FRAMES;
  Serial.printf("RX Raw: %d edges\n", count);
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

  // *IDN? - Identification
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-IR,1.0,2026\n");
  }

  // *RST - Reset
  else if (strcmp(cmd, "*RST") == 0) {
    rx_read_idx = rx_write_idx = 0;
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // IR:SEND:NEC,<addr>,<cmd> - Send NEC protocol
  else if (strncmp(cmd, "IR:SEND:NEC", 11) == 0) {
    int addr, command;
    if (sscanf(cmd + 11, ",%d,%d", &addr, &command) == 2) {
      send_nec(addr, command);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // IR:SEND:RC5,<addr>,<cmd> - Send RC5 protocol
  else if (strncmp(cmd, "IR:SEND:RC5", 11) == 0) {
    int addr, command;
    if (sscanf(cmd + 11, ",%d,%d", &addr, &command) == 2) {
      send_rc5(addr, command, false);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // IR:SEND:SONY,<addr>,<cmd>,<bits> - Send Sony SIRC protocol
  else if (strncmp(cmd, "IR:SEND:SONY", 12) == 0) {
    int addr, command, bits;
    if (sscanf(cmd + 12, ",%d,%d,%d", &addr, &command, &bits) == 3) {
      send_sony(addr, command, bits);
      send_response("OK\n");
    } else {
      send_response("ERROR: Invalid parameters\n");
    }
  }

  // IR:SEND:RAW,<freq>,<us1>,<us2>,... - Send raw timings
  else if (strncmp(cmd, "IR:SEND:RAW", 11) == 0) {
    uint32_t freq;
    uint16_t timings[256];
    int count = 0;

    char* p = cmd + 11;
    if (sscanf(p, ",%lu", &freq) == 1) {
      p = strchr(p + 1, ',');
      while (p && count < 256) {
        int timing;
        if (sscanf(p, ",%d", &timing) == 1) {
          timings[count++] = timing;
          p = strchr(p + 1, ',');
        } else {
          break;
        }
      }

      if (count > 0) {
        send_raw(freq, timings, count);
        send_response("OK\n");
      } else {
        send_response("ERROR: No timings provided\n");
      }
    } else {
      send_response("ERROR: Invalid frequency\n");
    }
  }

  // IR:RECV? - Read next decoded frame
  else if (strcmp(cmd, "IR:RECV?") == 0) {
    if (rx_read_idx != rx_write_idx) {
      volatile IRFrame* frame = &rx_buffer[rx_read_idx];
      char response[128];

      if (frame->protocol == 0) {  // NEC
        snprintf(response, sizeof(response), "NEC,%lu,%lu\n",
                 frame->address, frame->command);
      } else if (frame->protocol == 3) {  // Raw
        snprintf(response, sizeof(response), "RAW,%u\n", frame->raw_count);
      } else {
        snprintf(response, sizeof(response), "UNKNOWN\n");
      }

      rx_read_idx = (rx_read_idx + 1) % MAX_RX_FRAMES;
      send_response(response);
    } else {
      send_response("EMPTY\n");
    }
  }

  // IR:RECV:RAW? - Read raw timings from last frame
  else if (strcmp(cmd, "IR:RECV:RAW?") == 0) {
    if (rx_read_idx != rx_write_idx) {
      volatile IRFrame* frame = &rx_buffer[rx_read_idx];
      char response[2048];
      int len = 0;

      for (int i = 0; i < frame->raw_count && len < sizeof(response) - 16; i++) {
        len += snprintf(response + len, sizeof(response) - len,
                       "%u%s", frame->raw_data[i],
                       (i < frame->raw_count - 1) ? "," : "\n");
      }

      rx_read_idx = (rx_read_idx + 1) % MAX_RX_FRAMES;
      send_response(response);
    } else {
      send_response("EMPTY\n");
    }
  }

  // IR:AVAI? - Query frames available
  else if (strcmp(cmd, "IR:AVAI?") == 0) {
    int available = (rx_write_idx - rx_read_idx + MAX_RX_FRAMES) % MAX_RX_FRAMES;
    char response[16];
    snprintf(response, sizeof(response), "%d\n", available);
    send_response(response);
  }

  // IR:CARR,<khz> - Set carrier frequency
  else if (strncmp(cmd, "IR:CARR", 7) == 0) {
    int freq_khz;
    if (sscanf(cmd + 7, ",%d", &freq_khz) == 1) {
      if (freq_khz >= 30 && freq_khz <= 60) {
        carrier_freq_hz = freq_khz * 1000;
        carrier_period_us = 1000000UL / carrier_freq_hz;
        ledcSetup(pwm_channel, carrier_freq_hz, pwm_resolution);
        send_response("OK\n");
      } else {
        send_response("ERROR: Frequency out of range (30-60 kHz)\n");
      }
    } else {
      send_response("ERROR: Invalid frequency\n");
    }
  }

  // IR:CARR? - Query carrier frequency
  else if (strcmp(cmd, "IR:CARR?") == 0) {
    char response[16];
    snprintf(response, sizeof(response), "%lu\n", carrier_freq_hz / 1000);
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}

// Send NEC protocol IR code
void send_nec(uint16_t addr, uint8_t cmd) {
  // NEC format: 9ms mark, 4.5ms space, 32 bits (addr, ~addr, cmd, ~cmd)
  mark(9000);
  space(4500);

  uint32_t data = ((uint32_t)addr << 24) |
                  ((uint32_t)(~addr & 0xFF) << 16) |
                  ((uint32_t)cmd << 8) |
                  (uint32_t)(~cmd & 0xFF);

  for (int i = 0; i < 32; i++) {
    mark(560);
    if (data & (1UL << i)) {
      space(1690);  // Logical 1
    } else {
      space(560);   // Logical 0
    }
  }

  mark(560);  // Stop bit
  disable_carrier();

  Serial.printf("TX NEC: addr=0x%02X cmd=0x%02X\n", addr, cmd);
}

// Send RC5 protocol IR code
void send_rc5(uint8_t addr, uint8_t cmd, bool toggle) {
  // RC5 format: Manchester encoding, 889us half-bit periods
  // 2 start bits (1,1), 1 toggle bit, 5 address bits, 6 command bits
  const int half_bit_us = 889;

  uint16_t data = 0x3000 |  // Start bits
                  (toggle ? 0x0800 : 0) |
                  ((addr & 0x1F) << 6) |
                  (cmd & 0x3F);

  // Manchester encode and send
  for (int i = 13; i >= 0; i--) {
    if (data & (1 << i)) {
      space(half_bit_us);
      mark(half_bit_us);
    } else {
      mark(half_bit_us);
      space(half_bit_us);
    }
  }

  disable_carrier();
  Serial.printf("TX RC5: addr=%d cmd=%d toggle=%d\n", addr, cmd, toggle);
}

// Send Sony SIRC protocol IR code
void send_sony(uint16_t addr, uint8_t cmd, uint8_t bits) {
  // Sony SIRC: 2.4ms mark header, then data bits (600us mark + 600/1200us space)
  mark(2400);

  // Command bits (7 bits)
  for (int i = 0; i < 7; i++) {
    mark(600);
    space((cmd & (1 << i)) ? 1200 : 600);
  }

  // Address bits (variable: 5 bits for SIRC-12, 8 for SIRC-15, 13 for SIRC-20)
  int addr_bits = bits - 7;
  for (int i = 0; i < addr_bits; i++) {
    mark(600);
    space((addr & (1 << i)) ? 1200 : 600);
  }

  disable_carrier();
  Serial.printf("TX Sony: addr=0x%02X cmd=0x%02X bits=%d\n", addr, cmd, bits);
}

// Send raw IR timings
void send_raw(uint32_t freq, const uint16_t* timings, uint16_t count) {
  uint32_t old_freq = carrier_freq_hz;

  if (freq != carrier_freq_hz) {
    carrier_freq_hz = freq;
    carrier_period_us = 1000000UL / carrier_freq_hz;
    ledcSetup(pwm_channel, carrier_freq_hz, pwm_resolution);
  }

  for (uint16_t i = 0; i < count; i++) {
    if (i % 2 == 0) {
      mark(timings[i]);
    } else {
      space(timings[i]);
    }
  }

  disable_carrier();

  if (freq != old_freq) {
    carrier_freq_hz = old_freq;
    carrier_period_us = 1000000UL / carrier_freq_hz;
    ledcSetup(pwm_channel, carrier_freq_hz, pwm_resolution);
  }

  Serial.printf("TX Raw: %d timings at %lu kHz\n", count, freq / 1000);
}

// Mark (carrier on)
void mark(uint16_t us) {
  ledcWrite(pwm_channel, pwm_duty);  // 50% duty cycle
  delayMicroseconds(us);
}

// Space (carrier off)
void space(uint16_t us) {
  ledcWrite(pwm_channel, 0);
  delayMicroseconds(us);
}

// Enable carrier at specified frequency
void enable_carrier(uint32_t freq_hz) {
  carrier_freq_hz = freq_hz;
  carrier_period_us = 1000000UL / carrier_freq_hz;
  ledcSetup(pwm_channel, carrier_freq_hz, pwm_resolution);
  ledcWrite(pwm_channel, pwm_duty);
  carrier_enabled = true;
}

// Disable carrier
void disable_carrier() {
  ledcWrite(pwm_channel, 0);
  carrier_enabled = false;
}
