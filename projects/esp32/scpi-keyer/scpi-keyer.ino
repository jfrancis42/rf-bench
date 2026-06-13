/*
 * SCPI CW Keyer for ESP32
 *
 * Network-controlled CW (Morse code) keyer with iambic paddle support,
 * straight key mode, and automatic text transmission via SCPI commands.
 *
 * Hardware connections:
 *   KEY output -> GPIO 25 (to rig key input, open-drain)
 *   PTT output -> GPIO 26 (pre-TX delay before keying, open-drain)
 *   DIT paddle -> GPIO 32 (pull-up, active-low)
 *   DAH paddle -> GPIO 33 (pull-up, active-low)
 *   Straight key -> GPIO 34 (pull-up, active-low, optional)
 *   Sidetone speaker -> GPIO 23 (PWM tone output)
 *
 * Open-drain outputs suitable for most rigs (pull to ground when active).
 * PTT activates before KEY (configurable delay) and releases after KEY
 * (configurable hang time) to allow amp/rig sequencing.
 *
 * Iambic mode B: Both paddles → alternating dits/dahs until one released.
 * Straight key mode: GPIO 34 directly controls KEY output.
 *
 * Sidetone: Optional audio feedback on GPIO 23. Configurable frequency
 * (300-1200 Hz) and duration (0 = disabled, >0 = tone during keying).
 */

#include <WiFi.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// GPIO pin assignments
const int key_pin = 25;        // KEY output (open-drain, to rig)
const int ptt_pin = 26;        // PTT output (open-drain, pre-TX delay)
const int dit_pin = 32;        // DIT paddle input (active-low with pull-up)
const int dah_pin = 33;        // DAH paddle input (active-low with pull-up)
const int straight_key_pin = 34; // Straight key input (active-low, optional)
const int tone_pin = 23;       // Sidetone output (PWM speaker)

// Keyer configuration
int wpm = 20;                  // CW speed (5-60 WPM)
bool iambic_mode = true;       // true = iambic mode B, false = straight key
int ptt_lead_ms = 50;          // PTT lead time before KEY (ms)
int ptt_tail_ms = 200;         // PTT hang time after KEY (ms)
int tone_freq_hz = 700;        // Sidetone frequency (300-1200 Hz)
int tone_duration_ms = 0;      // Sidetone duration (0 = disabled)

// Keyer timing (calculated from WPM)
int dit_duration_ms = 60;      // Duration of dit (updated by set_wpm)
int dah_duration_ms = 180;     // Duration of dah (3× dit)
int element_space_ms = 60;     // Space between elements (= dit)
int char_space_ms = 180;       // Space between characters (3× dit)
int word_space_ms = 420;       // Space between words (7× dit)

// Keyer state
bool key_down = false;         // Current KEY output state
bool ptt_active = false;       // Current PTT output state
bool sending_text = false;     // Currently sending SCPI text
unsigned long ptt_release_time = 0; // millis() when PTT can be released
volatile bool abort_requested = false; // Abort flag for text sending

// Iambic state machine
enum IambicState { IDLE, SENDING_DIT, SENDING_DAH, ELEMENT_SPACE };
IambicState iambic_state = IDLE;
unsigned long state_start_time = 0;
bool dit_latch = false;        // Iambic mode B: remember dit paddle during dah
bool dah_latch = false;        // Iambic mode B: remember dah paddle during dit

// Morse code lookup table (A-Z, 0-9, space)
// '.' = dit, '-' = dah, '\0' = end of character
const char* morse_table[37] = {
  ".-",    // A
  "-...",  // B
  "-.-.",  // C
  "-..",   // D
  ".",     // E
  "..-.",  // F
  "--.",   // G
  "....",  // H
  "..",    // I
  ".---",  // J
  "-.-",   // K
  ".-..",  // L
  "--",    // M
  "-.",    // N
  "---",   // O
  ".--.",  // P
  "--.-",  // Q
  ".-.",   // R
  "...",   // S
  "-",     // T
  "..-",   // U
  "...-",  // V
  ".--",   // W
  "-..-",  // X
  "-.--",  // Y
  "--..",  // Z
  "-----", // 0
  ".----", // 1
  "..---", // 2
  "...--", // 3
  "....-", // 4
  ".....", // 5
  "-....", // 6
  "--...", // 7
  "---..", // 8
  "----.", // 9
  ""       // Space (index 36)
};

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI CW Keyer");
  Serial.println("==============");

  // Initialize KEY output (default: key-up, idle-high for open-drain)
  pinMode(key_pin, OUTPUT);
  digitalWrite(key_pin, HIGH);

  // Initialize PTT output (default: RX mode, idle-high for open-drain)
  pinMode(ptt_pin, OUTPUT);
  digitalWrite(ptt_pin, HIGH);

  // Initialize paddle inputs with internal pull-up resistors
  pinMode(dit_pin, INPUT_PULLUP);
  pinMode(dah_pin, INPUT_PULLUP);
  pinMode(straight_key_pin, INPUT_PULLUP);

  // Initialize sidetone output (PWM)
  pinMode(tone_pin, OUTPUT);
  digitalWrite(tone_pin, LOW);

  // Calculate initial timing from WPM
  set_wpm(wpm);

  Serial.printf("Mode: %s\n", iambic_mode ? "Iambic B" : "Straight key");
  Serial.printf("Speed: %d WPM\n", wpm);
  Serial.printf("Dit: %d ms, Dah: %d ms\n", dit_duration_ms, dah_duration_ms);
  Serial.printf("PTT lead: %d ms, tail: %d ms\n", ptt_lead_ms, ptt_tail_ms);
  Serial.printf("Sidetone: %s (%d Hz)\n", tone_duration_ms > 0 ? "enabled" : "disabled", tone_freq_hz);

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

  // Keyer logic: iambic or straight key
  if (iambic_mode) {
    handle_iambic_paddles();
  } else {
    handle_straight_key();
  }

  // PTT hang time: release PTT after tail delay expires
  if (ptt_active && !key_down && !sending_text) {
    if (millis() >= ptt_release_time) {
      set_ptt(false);
    }
  }

  // Sidetone: turn off when key is released
  if (!key_down && tone_duration_ms > 0) {
    noTone(tone_pin);
  }
}

// Set CW speed in WPM (5-60)
void set_wpm(int new_wpm) {
  if (new_wpm < 5) new_wpm = 5;
  if (new_wpm > 60) new_wpm = 60;
  wpm = new_wpm;

  // PARIS standard: 50 dit-lengths per word
  // Dit duration (ms) = 1200 / WPM
  dit_duration_ms = 1200 / wpm;
  dah_duration_ms = dit_duration_ms * 3;
  element_space_ms = dit_duration_ms;
  char_space_ms = dit_duration_ms * 3;
  word_space_ms = dit_duration_ms * 7;
}

// Set physical KEY output
void set_key(bool state) {
  key_down = state;
  // Open-drain: LOW = key down (TX), HIGH = key up (idle)
  digitalWrite(key_pin, state ? LOW : HIGH);

  if (state) {
    // Key down: ensure PTT is active and extend release time
    if (!ptt_active) {
      set_ptt(true);
      delay(ptt_lead_ms); // Wait for PTT lead time
    }
    ptt_release_time = millis() + ptt_tail_ms;

    // Sidetone
    if (tone_duration_ms > 0) {
      tone(tone_pin, tone_freq_hz);
    }
  } else {
    // Key up: sidetone off is handled in loop()
    // PTT release is deferred until ptt_tail_ms expires
  }
}

// Set physical PTT output
void set_ptt(bool state) {
  ptt_active = state;
  // Open-drain: LOW = TX, HIGH = RX
  digitalWrite(ptt_pin, state ? LOW : HIGH);
}

// Handle iambic paddle inputs (mode B)
void handle_iambic_paddles() {
  bool dit_pressed = (digitalRead(dit_pin) == LOW);
  bool dah_pressed = (digitalRead(dah_pin) == LOW);

  switch (iambic_state) {
    case IDLE:
      if (dit_pressed) {
        iambic_state = SENDING_DIT;
        state_start_time = millis();
        set_key(true);
        dah_latch = false; // Clear latch at start of new sequence
      } else if (dah_pressed) {
        iambic_state = SENDING_DAH;
        state_start_time = millis();
        set_key(true);
        dit_latch = false; // Clear latch at start of new sequence
      }
      break;

    case SENDING_DIT:
      // Remember dah paddle press during dit (mode B)
      if (dah_pressed) {
        dah_latch = true;
      }

      if (millis() - state_start_time >= dit_duration_ms) {
        set_key(false);
        iambic_state = ELEMENT_SPACE;
        state_start_time = millis();
      }
      break;

    case SENDING_DAH:
      // Remember dit paddle press during dah (mode B)
      if (dit_pressed) {
        dit_latch = true;
      }

      if (millis() - state_start_time >= dah_duration_ms) {
        set_key(false);
        iambic_state = ELEMENT_SPACE;
        state_start_time = millis();
      }
      break;

    case ELEMENT_SPACE:
      if (millis() - state_start_time >= element_space_ms) {
        // Check latches and current paddle state to decide next element
        if (dah_latch || (dah_pressed && !dit_latch)) {
          iambic_state = SENDING_DAH;
          state_start_time = millis();
          set_key(true);
          dit_latch = false;
          dah_latch = false;
        } else if (dit_latch || dit_pressed) {
          iambic_state = SENDING_DIT;
          state_start_time = millis();
          set_key(true);
          dit_latch = false;
          dah_latch = false;
        } else {
          // No paddles pressed, no latches -> idle
          iambic_state = IDLE;
        }
      }
      break;
  }
}

// Handle straight key input
void handle_straight_key() {
  bool key_pressed = (digitalRead(straight_key_pin) == LOW);
  set_key(key_pressed);
}

// Send a single morse element (dit or dah)
void send_element(bool is_dah) {
  if (abort_requested) return;

  int duration = is_dah ? dah_duration_ms : dit_duration_ms;
  set_key(true);
  delay(duration);
  set_key(false);
  delay(element_space_ms);
}

// Send a morse character (A-Z, 0-9, space)
void send_char(char c) {
  if (abort_requested) return;

  c = toupper(c);
  int index = -1;

  if (c >= 'A' && c <= 'Z') {
    index = c - 'A';
  } else if (c >= '0' && c <= '9') {
    index = 26 + (c - '0');
  } else if (c == ' ') {
    index = 36;
  }

  if (index == 36) {
    // Space: add word space (total = char_space + word_space - char_space = word_space)
    delay(word_space_ms - char_space_ms);
    return;
  }

  if (index >= 0 && index < 36) {
    const char* pattern = morse_table[index];
    for (int i = 0; pattern[i] != '\0'; i++) {
      if (abort_requested) return;
      send_element(pattern[i] == '-');
    }
    // Character space (already had element_space after last element)
    delay(char_space_ms - element_space_ms);
  }
}

// Send text string
void send_text(const char* text) {
  abort_requested = false;
  sending_text = true;

  // Activate PTT before sending
  set_ptt(true);
  delay(ptt_lead_ms);

  for (int i = 0; text[i] != '\0'; i++) {
    if (abort_requested) break;
    send_char(text[i]);
  }

  sending_text = false;
  ptt_release_time = millis() + ptt_tail_ms;

  if (abort_requested) {
    Serial.println("Text sending aborted");
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

  char response[128];

  // *IDN? - Identification query
  if (strcmp(cmd, "*IDN?") == 0) {
    send_response("N0GQ,ESP32-SCPI-Keyer,1.0,2026\n");
  }

  // *RST - Reset (20 WPM, iambic mode, sidetone off)
  else if (strcmp(cmd, "*RST") == 0) {
    abort_requested = true;
    delay(100); // Allow current sending to abort
    set_key(false);
    set_ptt(false);
    iambic_mode = true;
    set_wpm(20);
    tone_duration_ms = 0;
    send_response("OK\n");
    Serial.println("Reset: 20 WPM, iambic mode, sidetone off");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // KEY:WPM,<5-60> - Set speed
  else if (strncmp(cmd, "KEY:WPM,", 8) == 0) {
    int new_wpm = -1;
    sscanf(cmd + 8, "%d", &new_wpm);

    if (new_wpm >= 5 && new_wpm <= 60) {
      set_wpm(new_wpm);
      send_response("OK\n");
      Serial.printf("Speed: %d WPM (dit=%d ms, dah=%d ms)\n", wpm, dit_duration_ms, dah_duration_ms);
    } else {
      send_response("ERROR: Invalid WPM (must be 5-60)\n");
    }
  }

  // KEY:WPM? - Query speed
  else if (strcmp(cmd, "KEY:WPM?") == 0) {
    snprintf(response, sizeof(response), "%d\n", wpm);
    send_response(response);
  }

  // KEY:MODE,<IAMB|STRK> - Set keying mode
  else if (strncmp(cmd, "KEY:MODE,", 9) == 0) {
    const char* mode = cmd + 9;
    if (strcmp(mode, "IAMB") == 0 || strcmp(mode, "IAMBIC") == 0) {
      iambic_mode = true;
      send_response("OK\n");
      Serial.println("Mode: Iambic B");
    } else if (strcmp(mode, "STRK") == 0 || strcmp(mode, "STRAIGHT") == 0) {
      iambic_mode = false;
      send_response("OK\n");
      Serial.println("Mode: Straight key");
    } else {
      send_response("ERROR: Invalid mode (IAMB or STRK)\n");
    }
  }

  // KEY:MODE? - Query mode
  else if (strcmp(cmd, "KEY:MODE?") == 0) {
    send_response(iambic_mode ? "IAMB\n" : "STRK\n");
  }

  // KEY:SEND,<text> - Send CW text
  else if (strncmp(cmd, "KEY:SEND,", 9) == 0) {
    const char* text = cmd + 9;
    Serial.printf("Sending: %s\n", text);
    send_text(text);
    send_response("OK\n");
  }

  // KEY:TON,<ms> - Set sidetone duration (0 = disabled)
  else if (strncmp(cmd, "KEY:TON,", 8) == 0 || strncmp(cmd, "KEY:TONE,", 9) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int duration = -1;
      sscanf(comma + 1, "%d", &duration);

      if (duration >= 0) {
        tone_duration_ms = duration;
        send_response("OK\n");
        Serial.printf("Sidetone: %s\n", tone_duration_ms > 0 ? "enabled" : "disabled");
      } else {
        send_response("ERROR: Invalid duration (must be >= 0)\n");
      }
    } else {
      send_response("ERROR: Invalid command format\n");
    }
  }

  // KEY:TON? - Query sidetone duration
  else if (strcmp(cmd, "KEY:TON?") == 0 || strcmp(cmd, "KEY:TONE?") == 0) {
    snprintf(response, sizeof(response), "%d\n", tone_duration_ms);
    send_response(response);
  }

  // KEY:FREQ,<hz> - Set sidetone frequency (300-1200 Hz)
  else if (strncmp(cmd, "KEY:FREQ,", 9) == 0) {
    int freq = -1;
    sscanf(cmd + 9, "%d", &freq);

    if (freq >= 300 && freq <= 1200) {
      tone_freq_hz = freq;
      send_response("OK\n");
      Serial.printf("Sidetone frequency: %d Hz\n", tone_freq_hz);
    } else {
      send_response("ERROR: Invalid frequency (must be 300-1200 Hz)\n");
    }
  }

  // KEY:FREQ? - Query sidetone frequency
  else if (strcmp(cmd, "KEY:FREQ?") == 0) {
    snprintf(response, sizeof(response), "%d\n", tone_freq_hz);
    send_response(response);
  }

  // KEY:STAT? - Query keying state (0 = idle, 1 = keying)
  else if (strcmp(cmd, "KEY:STAT?") == 0 || strcmp(cmd, "KEY:STATUS?") == 0) {
    snprintf(response, sizeof(response), "%d\n", key_down ? 1 : 0);
    send_response(response);
  }

  // KEY:ABOR - Abort sending
  else if (strcmp(cmd, "KEY:ABOR") == 0 || strcmp(cmd, "KEY:ABORT") == 0) {
    abort_requested = true;
    send_response("OK\n");
    Serial.println("Abort requested");
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
