/*
 * Arduino + Wiznet W5100 network-controlled 4-channel relay board.
 *
 * Hardware:
 *   Arduino Uno R3 / Nano / Mega + Vilros Ethernet R3 shield
 *   (clone of the official Arduino Ethernet Shield R3 — same wiring,
 *   W5100 chip, on-board microSD card slot).
 *
 *   The stock Arduino `Ethernet` library v2.x supports W5100 and W5500
 *   transparently (auto-detects at `Ethernet.begin()`), so this sketch
 *   also runs unchanged if you ever swap to a W5500-based shield —
 *   only the socket count differs (W5100 has 4, W5500 has 8; see
 *   MAX_CLIENTS below).
 *
 * Pins consumed by the shield (do NOT use these for relays):
 *   D4   -> microSD card CS    (not used by this sketch, but kept HIGH
 *                                in setup() to deselect the SD card so
 *                                it doesn't fight on the SPI bus)
 *   D10  -> W5100 CS
 *   D11  -> SPI MOSI (shared with W5100 and SD)
 *   D12  -> SPI MISO (shared with W5100 and SD)
 *   D13  -> SPI SCK  (shared with W5100 and SD)
 *   D2   -> W5100 INT (optional; not used by the Ethernet library)
 *   On Mega 2560 the shield routes SPI via the ICSP header (D50/D51/D52);
 *   D10 is still W5100 CS, D4 is still SD CS.
 *
 * Relay outputs (one pin per relay, active-low by default — change
 * RELAY_ACTIVE_HIGH to true for active-high boards):
 *   D5 -> Relay 1   D6 -> Relay 2   D7 -> Relay 3   D8 -> Relay 4
 *
 * D9 is intentionally skipped (free, but kept as a margin so any
 * future shield variant that uses it for an interrupt is fine).
 *
 * MAC address: locally-administered (0x02 in first byte). Change BOARD_ID
 * if you run more than one of these on the same LAN.
 *
 * Network: DHCP. If DHCP fails, falls back to a static 192.168.1.177.
 *
 * Protocol: line-oriented ASCII over TCP, port 5025.  Every command
 * produces exactly one response line ending in '\n'.
 *   ON n           -> OK              (relay n on)
 *   OFF n          -> OK              (relay n off)
 *   PULSEH n ms    -> OK              (drive HIGH for ms ms, return LOW)
 *   PULSEL n ms    -> OK              (drive LOW for ms ms, return HIGH)
 *   STATUS n       -> 0|1
 *   STATUS         -> 0xH             (4-bit bitmask, bit 0 = relay 1)
 *   *IDN?          -> N0GQ,ArduinoRelayBoard,1.0,2026
 *   RESET          -> OK              (all relays off)
 *   HELP           -> banner of commands
 *
 *   On error:        ERR: <reason>
 *
 * The pulse implementation is non-blocking: a 60-second PULSE will not
 * freeze the network or stall other commands.
 */

#include <SPI.h>
#include <Ethernet.h>

// ---- configuration ------------------------------------------------------

static const uint8_t BOARD_ID = 0x01;       // bump for additional units on the LAN
static const uint16_t LISTEN_PORT = 5025;   // rf-bench / SCPI convention

// Relay control pins (one per relay)
static const uint8_t NUM_RELAYS = 4;
static const uint8_t RELAY_PINS[NUM_RELAYS] = {5, 6, 7, 8};

// Polarity of the relay control inputs.
//   true  -> drive pin HIGH to energize  (this board)
//   false -> drive pin LOW to energize   (typical cheap SainSmart-style modules)
// Flip if you swap to a different relay board and the states come out inverted.
static const bool RELAY_ACTIVE_HIGH = true;

// Fallback static IP if DHCP fails
static const IPAddress FALLBACK_IP(192, 168, 1, 177);

// Max simultaneous TCP clients.
//   W5100: 4 hardware sockets total — one is consumed by the listening
//          server, leaving 3 for accepted clients.
//   W5500: 8 hardware sockets total — same sketch works with more room
//          (bump this to 6 or 7 if you swap in a W5500 and want it).
static const uint8_t MAX_CLIENTS = 3;

// ---- state --------------------------------------------------------------

// Logical relay state (true = energized).
static bool relay_state[NUM_RELAYS] = {false, false, false, false};

// Non-blocking pulse tracking. expire_ms = 0 means "no pulse active".
struct Pulse {
  unsigned long expire_ms;   // millis() value at which to revert
  bool revert_to_state;      // logical state to revert to (false = OFF, true = ON)
};
static Pulse pulses[NUM_RELAYS] = {{0, false}, {0, false}, {0, false}, {0, false}};

// Per-client tracking. We keep the EthernetClient object alongside the
// line-accumulation buffer so partial commands from different clients
// don't get interleaved. EthernetClient::operator bool() is true while
// the underlying socket is allocated; we use that to detect a free slot.
struct ClientSlot {
  EthernetClient client;
  char buf[96];
  uint8_t len;
};
static ClientSlot clients[MAX_CLIENTS];

EthernetServer server(LISTEN_PORT);

// ---- relay helpers ------------------------------------------------------

static void write_relay_hw(uint8_t i, bool energize) {
  bool pin_high = RELAY_ACTIVE_HIGH ? energize : !energize;
  digitalWrite(RELAY_PINS[i], pin_high ? HIGH : LOW);
  relay_state[i] = energize;
}

static void set_relay(uint8_t i, bool energize) {
  // Setting a relay explicitly cancels any in-flight pulse on it.
  pulses[i].expire_ms = 0;
  write_relay_hw(i, energize);
}

static void start_pulse(uint8_t i, bool active_state, unsigned long duration_ms) {
  // Drive to active_state now; schedule revert to !active_state after duration_ms.
  write_relay_hw(i, active_state);
  pulses[i].revert_to_state = !active_state;
  pulses[i].expire_ms = millis() + duration_ms;
  if (pulses[i].expire_ms == 0) pulses[i].expire_ms = 1;  // 0 reserved as "inactive"
}

static void service_pulses() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_RELAYS; i++) {
    if (pulses[i].expire_ms != 0) {
      // Handle millis() wraparound safely with signed subtraction
      long delta = (long)(now - pulses[i].expire_ms);
      if (delta >= 0) {
        write_relay_hw(i, pulses[i].revert_to_state);
        pulses[i].expire_ms = 0;
      }
    }
  }
}

static uint8_t status_bitmask() {
  uint8_t m = 0;
  for (uint8_t i = 0; i < NUM_RELAYS; i++) {
    if (relay_state[i]) m |= (1 << i);
  }
  return m;
}

// ---- command parsing ----------------------------------------------------

// Trim trailing whitespace in-place, return new length.
static uint8_t rstrip(char *s, uint8_t len) {
  while (len > 0 && (s[len - 1] == ' ' || s[len - 1] == '\t' ||
                     s[len - 1] == '\r' || s[len - 1] == '\n')) {
    s[--len] = '\0';
  }
  return len;
}

// Uppercase a string in-place.
static void to_upper(char *s) {
  for (; *s; s++) {
    if (*s >= 'a' && *s <= 'z') *s -= 32;
  }
}

// Parse a relay index (1..NUM_RELAYS) starting at *p. Returns 0..NUM_RELAYS-1
// on success, -1 on parse error. Advances *p past the number on success.
static int parse_relay_index(const char **p) {
  while (**p == ' ' || **p == '\t') (*p)++;
  if (**p < '0' || **p > '9') return -1;
  int n = 0;
  while (**p >= '0' && **p <= '9') {
    n = n * 10 + (**p - '0');
    (*p)++;
  }
  if (n < 1 || n > (int)NUM_RELAYS) return -1;
  return n - 1;
}

// Parse an unsigned millisecond duration. Returns 0xFFFFFFFFUL on error.
static unsigned long parse_ms(const char **p) {
  while (**p == ' ' || **p == '\t') (*p)++;
  if (**p < '0' || **p > '9') return 0xFFFFFFFFUL;
  unsigned long n = 0;
  while (**p >= '0' && **p <= '9') {
    n = n * 10UL + (unsigned long)(**p - '0');
    (*p)++;
  }
  return n;
}

// Send a response line to the given client.
static void respond(EthernetClient &c, const char *s) {
  c.print(s);
  c.print('\n');
}

static void cmd_help(EthernetClient &c) {
  c.println(F("Commands:"));
  c.println(F("  ON <n>            energize relay n (1-4)"));
  c.println(F("  OFF <n>           de-energize relay n"));
  c.println(F("  PULSEH <n> <ms>   drive HIGH for ms milliseconds, then LOW"));
  c.println(F("  PULSEL <n> <ms>   drive LOW for ms milliseconds, then HIGH"));
  c.println(F("  STATUS <n>        query one relay (0 or 1)"));
  c.println(F("  STATUS            query all (4-bit hex bitmask, bit 0 = relay 1)"));
  c.println(F("  *IDN?             identification"));
  c.println(F("  RESET             all relays off, cancel all pulses"));
  c.println(F("  HELP              this banner"));
  c.println(F("END"));
}

static void process_line(EthernetClient &c, char *line) {
  to_upper(line);

  // Skip empty / whitespace-only lines silently? No — protocol promises
  // exactly one response per command. Treat empty as error.
  const char *p = line;
  while (*p == ' ' || *p == '\t') p++;
  if (*p == '\0') {
    respond(c, "ERR: empty command");
    return;
  }

  if (strcmp(p, "*IDN?") == 0) {
    char buf[64];
    snprintf(buf, sizeof(buf), "N0GQ,ArduinoRelayBoard,1.0,2026,id=%u", BOARD_ID);
    respond(c, buf);
    return;
  }

  if (strcmp(p, "HELP") == 0 || strcmp(p, "?") == 0) {
    cmd_help(c);
    return;
  }

  if (strcmp(p, "RESET") == 0 || strcmp(p, "*RST") == 0) {
    for (uint8_t i = 0; i < NUM_RELAYS; i++) set_relay(i, false);
    respond(c, "OK");
    return;
  }

  if (strncmp(p, "STATUS", 6) == 0) {
    p += 6;
    while (*p == ' ' || *p == '\t') p++;
    if (*p == '\0') {
      // Whole-board query
      char buf[8];
      snprintf(buf, sizeof(buf), "0x%X", status_bitmask());
      respond(c, buf);
    } else {
      int r = parse_relay_index(&p);
      if (r < 0) { respond(c, "ERR: bad relay index"); return; }
      respond(c, relay_state[r] ? "1" : "0");
    }
    return;
  }

  if (strncmp(p, "ON", 2) == 0 && (p[2] == ' ' || p[2] == '\t')) {
    p += 2;
    int r = parse_relay_index(&p);
    if (r < 0) { respond(c, "ERR: bad relay index"); return; }
    set_relay(r, true);
    respond(c, "OK");
    return;
  }

  if (strncmp(p, "OFF", 3) == 0 && (p[3] == ' ' || p[3] == '\t')) {
    p += 3;
    int r = parse_relay_index(&p);
    if (r < 0) { respond(c, "ERR: bad relay index"); return; }
    set_relay(r, false);
    respond(c, "OK");
    return;
  }

  if (strncmp(p, "PULSEH", 6) == 0 && (p[6] == ' ' || p[6] == '\t')) {
    p += 6;
    int r = parse_relay_index(&p);
    if (r < 0) { respond(c, "ERR: bad relay index"); return; }
    unsigned long ms = parse_ms(&p);
    if (ms == 0xFFFFFFFFUL || ms == 0) {
      respond(c, "ERR: bad duration"); return;
    }
    start_pulse(r, true, ms);
    respond(c, "OK");
    return;
  }

  if (strncmp(p, "PULSEL", 6) == 0 && (p[6] == ' ' || p[6] == '\t')) {
    p += 6;
    int r = parse_relay_index(&p);
    if (r < 0) { respond(c, "ERR: bad relay index"); return; }
    unsigned long ms = parse_ms(&p);
    if (ms == 0xFFFFFFFFUL || ms == 0) {
      respond(c, "ERR: bad duration"); return;
    }
    start_pulse(r, false, ms);
    respond(c, "OK");
    return;
  }

  respond(c, "ERR: unknown command");
}

// ---- arduino entry points ----------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(50);
  Serial.println(F("\nArduino W5100 Relay Board"));
  Serial.println(F("========================="));

  // Deselect the microSD card on the Vilros / Arduino Ethernet R3 shield.
  // The SD card's CS line (D4) shares SPI with the W5100; if left floating
  // it can be pulled low by noise and the SD chip will scramble bytes on
  // every Ethernet transfer.  We never use the SD in this project, but we
  // must explicitly drive D4 HIGH to keep the SD chip off the bus.
  pinMode(4, OUTPUT);
  digitalWrite(4, HIGH);

  // Initialize relays to OFF before doing anything else (avoids
  // momentary on-glitch on power-up because pins default to INPUT/LOW
  // and most active-low boards see that as "on").
  for (uint8_t i = 0; i < NUM_RELAYS; i++) {
    pinMode(RELAY_PINS[i], OUTPUT);
    write_relay_hw(i, false);
  }

  // Locally-administered MAC: 02:xx:xx:xx:xx:BOARD_ID
  byte mac[6] = { 0x02, 0xAB, 0xCD, 0xEF, 0x42, BOARD_ID };

  Serial.print(F("MAC:  "));
  for (uint8_t i = 0; i < 6; i++) {
    if (mac[i] < 0x10) Serial.print('0');
    Serial.print(mac[i], HEX);
    if (i < 5) Serial.print(':');
  }
  Serial.println();

  Serial.print(F("DHCP... "));
  bool got_dhcp = (Ethernet.begin(mac) != 0);
  if (got_dhcp) {
    Serial.println(F("ok"));
  } else {
    Serial.println(F("FAILED — falling back to static IP"));
    Ethernet.begin(mac, FALLBACK_IP);
  }

  // Detect missing hardware so the user knows what's wrong.
  EthernetHardwareStatus hw = Ethernet.hardwareStatus();
  if (hw == EthernetNoHardware) {
    Serial.println(F("ERROR: no Ethernet hardware detected — check wiring (CS=D10, MOSI/MISO/SCK on hw SPI)"));
  } else if (hw == EthernetW5100) {
    Serial.println(F("Detected: W5100 (4 sockets)"));
  } else if (hw == EthernetW5200) {
    Serial.println(F("Detected: W5200"));
  } else if (hw == EthernetW5500) {
    Serial.println(F("Detected: W5500 (8 sockets)"));
  }
  if (Ethernet.linkStatus() == LinkOFF) {
    Serial.println(F("WARNING: Ethernet link is DOWN — plug in cable"));
  }

  // Print network configuration prominently — this is the address you
  // point clients at.
  Serial.println();
  Serial.println(F("----- network -----"));
  Serial.print(F("  IP address : "));  Serial.println(Ethernet.localIP());
  Serial.print(F("  Subnet mask: "));  Serial.println(Ethernet.subnetMask());
  Serial.print(F("  Gateway    : "));  Serial.println(Ethernet.gatewayIP());
  Serial.print(F("  DNS server : "));  Serial.println(Ethernet.dnsServerIP());
  Serial.print(F("  TCP port   : "));  Serial.println(LISTEN_PORT);
  Serial.print(F("  Source     : "));
  Serial.println(got_dhcp ? F("DHCP") : F("static fallback"));
  Serial.println(F("-------------------"));
  Serial.println();

  server.begin();
  Serial.println(F("Ready."));
}

// Run Ethernet.maintain() and report DHCP lease events on the serial
// console. Return codes from the library:
//   0 = nothing happened     1 = renew failed     2 = renew succeeded
//   3 = rebind failed        4 = rebind succeeded
static void maintain_dhcp_with_reporting() {
  uint8_t r = Ethernet.maintain();
  if (r == 0) return;
  switch (r) {
    case 1: Serial.println(F("DHCP: lease renewal FAILED")); break;
    case 2:
      Serial.print(F("DHCP: lease renewed, IP="));
      Serial.println(Ethernet.localIP());
      break;
    case 3: Serial.println(F("DHCP: rebind FAILED")); break;
    case 4:
      Serial.print(F("DHCP: rebind ok, IP="));
      Serial.println(Ethernet.localIP());
      break;
  }
}

// Try to accept any newly-connected client into a free ClientSlot.
// Uses EthernetClient::operator== so we don't double-register a client
// that's already in a slot. Portable across Arduino Ethernet versions.
static void accept_new_client() {
  EthernetClient nc = server.accept();
  if (!nc) return;

  // Is it already in a slot (defensive — accept() should only return
  // each socket once, but check anyway)?
  for (uint8_t i = 0; i < MAX_CLIENTS; i++) {
    if (clients[i].client && clients[i].client == nc) {
      return;
    }
  }
  // Find a free slot.
  for (uint8_t i = 0; i < MAX_CLIENTS; i++) {
    if (!clients[i].client) {
      clients[i].client = nc;
      clients[i].len = 0;
      return;
    }
  }
  // No free slot — refuse politely and drop the connection.
  nc.println(F("ERR: server busy"));
  nc.stop();
}

// Service one client slot: drain available bytes, dispatch on newline,
// and stop the socket if the peer disconnected.
static void service_client(uint8_t i) {
  ClientSlot &cs = clients[i];
  if (!cs.client) return;

  while (cs.client.available()) {
    int ci = cs.client.read();
    if (ci < 0) break;
    char ch = (char)ci;
    if (ch == '\n' || ch == '\r') {
      if (cs.len > 0) {
        cs.buf[cs.len] = '\0';
        rstrip(cs.buf, cs.len);
        process_line(cs.client, cs.buf);
        cs.len = 0;
      }
    } else if (cs.len < sizeof(cs.buf) - 1) {
      cs.buf[cs.len++] = ch;
    } else {
      cs.len = 0;
      respond(cs.client, "ERR: line too long");
    }
  }

  if (!cs.client.connected()) {
    cs.client.stop();
    cs.client = EthernetClient();   // mark slot free
    cs.len = 0;
  }
}

void loop() {
  // Maintain DHCP lease in the background; log lease events to serial.
  maintain_dhcp_with_reporting();

  // Service any pending pulse expirations.
  service_pulses();

  // Accept new TCP connections into a free slot.
  accept_new_client();

  // Service each known client.
  for (uint8_t i = 0; i < MAX_CLIENTS; i++) {
    service_client(i);
  }
}
