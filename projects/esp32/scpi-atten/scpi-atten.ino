/*
 * ESP32 SCPI RF Attenuator Controller
 *
 * Supports PE4302 (0-31.5 dB, 0.5 dB steps) and HMC472 (0-31 dB, 1 dB steps)
 * digital attenuators via SPI interface.
 *
 * Hardware connections:
 *   GPIO 18 -> CLK
 *   GPIO 23 -> DATA (MOSI)
 *   GPIO 5  -> LE (Latch Enable / Chip Select)
 *
 * Serial: 115200 baud, USB CDC
 *
 * SCPI Commands:
 *   ATT,<db>      Set attenuation (0-31.5 dB for PE4302, 0-31 dB for HMC472)
 *   ATT?          Query current attenuation
 *   ATT:STEP?     Query step size (0.5 or 1.0)
 *   ATT:MAX?      Query maximum attenuation
 *   ATT:DEV,<PE4302|HMC472>  Set device type
 *   ATT:DEV?      Query device type
 *   *IDN?         Identification string
 *   *RST          Reset to 0 dB
 */

#include <SPI.h>

// Pin definitions
#define PIN_CLK   18
#define PIN_DATA  23
#define PIN_LE    5

// Device types
enum DeviceType {
  DEV_PE4302,
  DEV_HMC472
};

// Device characteristics
struct DeviceSpec {
  const char* name;
  float maxAtten;
  float stepSize;
  uint8_t numBits;
};

const DeviceSpec specs[] = {
  {"PE4302", 31.5, 0.5, 6},  // PE4302: 6-bit, 0-63 = 0-31.5 dB
  {"HMC472", 31.0, 1.0, 5}   // HMC472: 5-bit, 0-31 = 0-31 dB
};

// Global state
DeviceType currentDevice = DEV_PE4302;
float currentAttenuation = 0.0;

// Command buffer
char cmdBuffer[128];
uint8_t cmdIndex = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    delay(10);
  }

  // Initialize SPI pins
  pinMode(PIN_LE, OUTPUT);
  digitalWrite(PIN_LE, LOW);

  SPI.begin(PIN_CLK, -1, PIN_DATA, -1);  // CLK, MISO (unused), MOSI, SS (unused)
  SPI.setFrequency(1000000);  // 1 MHz
  SPI.setDataMode(SPI_MODE0);
  SPI.setBitOrder(MSBFIRST);

  // Initialize to 0 dB
  setAttenuation(0.0);

  Serial.println("ESP32 SCPI RF Attenuator Ready");
  Serial.flush();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();

    // Handle line endings
    if (c == '\n' || c == '\r') {
      if (cmdIndex > 0) {
        cmdBuffer[cmdIndex] = '\0';
        processCommand(cmdBuffer);
        cmdIndex = 0;
      }
    }
    // Buffer overflow protection
    else if (cmdIndex < sizeof(cmdBuffer) - 1) {
      cmdBuffer[cmdIndex++] = c;
    }
    else {
      // Buffer full, discard and reset
      cmdIndex = 0;
      Serial.println("ERROR: Command too long");
    }
  }
}

void processCommand(char* cmd) {
  // Trim whitespace
  while (*cmd == ' ' || *cmd == '\t') cmd++;

  // Convert to uppercase for comparison
  String cmdStr = String(cmd);
  cmdStr.toUpperCase();
  cmdStr.trim();

  // Remove trailing whitespace
  int len = cmdStr.length();
  while (len > 0 && (cmdStr[len-1] == ' ' || cmdStr[len-1] == '\t')) {
    len--;
  }
  cmdStr = cmdStr.substring(0, len);

  // Parse and execute
  if (cmdStr.startsWith("ATT,")) {
    // Set attenuation
    float atten = cmdStr.substring(4).toFloat();
    if (setAttenuation(atten)) {
      Serial.println("OK");
    } else {
      Serial.println("ERROR: Invalid attenuation value");
    }
  }
  else if (cmdStr == "ATT?") {
    // Query attenuation
    Serial.println(currentAttenuation, (currentDevice == DEV_PE4302) ? 1 : 0);
  }
  else if (cmdStr == "ATT:STEP?") {
    // Query step size
    Serial.println(specs[currentDevice].stepSize, 1);
  }
  else if (cmdStr == "ATT:MAX?") {
    // Query max attenuation
    Serial.println(specs[currentDevice].maxAtten, 1);
  }
  else if (cmdStr.startsWith("ATT:DEV,")) {
    // Set device type
    String devName = cmdStr.substring(8);
    devName.trim();

    if (devName == "PE4302") {
      currentDevice = DEV_PE4302;
      setAttenuation(currentAttenuation);  // Re-apply with new device
      Serial.println("OK");
    }
    else if (devName == "HMC472") {
      currentDevice = DEV_HMC472;
      setAttenuation(currentAttenuation);  // Re-apply with new device
      Serial.println("OK");
    }
    else {
      Serial.println("ERROR: Unknown device type");
    }
  }
  else if (cmdStr == "ATT:DEV?") {
    // Query device type
    Serial.println(specs[currentDevice].name);
  }
  else if (cmdStr == "*IDN?") {
    // Identification
    Serial.println("N0GQ,ESP32-SCPI-ATTEN,1.0,2026");
  }
  else if (cmdStr == "*RST") {
    // Reset to 0 dB
    setAttenuation(0.0);
    Serial.println("OK");
  }
  else {
    Serial.println("ERROR: Unknown command");
  }
}

bool setAttenuation(float atten) {
  const DeviceSpec& spec = specs[currentDevice];

  // Validate range
  if (atten < 0.0 || atten > spec.maxAtten) {
    return false;
  }

  // Round to nearest step
  float steps = atten / spec.stepSize;
  uint8_t code = (uint8_t)(steps + 0.5);

  // Recalculate actual attenuation
  currentAttenuation = code * spec.stepSize;

  // Send to device
  writeAttenuator(code);

  return true;
}

void writeAttenuator(uint8_t code) {
  const DeviceSpec& spec = specs[currentDevice];

  // For PE4302: 6-bit code, LSB first
  // For HMC472: 5-bit code, MSB first (but we'll handle as 6-bit with MSB=0)

  digitalWrite(PIN_LE, LOW);
  delayMicroseconds(1);

  if (currentDevice == DEV_PE4302) {
    // PE4302: LSB first, 6 bits
    SPI.beginTransaction(SPISettings(1000000, LSBFIRST, SPI_MODE0));
    SPI.transfer(code & 0x3F);  // 6 bits
    SPI.endTransaction();
  }
  else {  // HMC472
    // HMC472: MSB first, 5 bits (send as 8-bit with upper bits zero)
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
    SPI.transfer((code & 0x1F) << 3);  // 5 bits left-justified in 8-bit word
    SPI.endTransaction();
  }

  delayMicroseconds(1);
  digitalWrite(PIN_LE, HIGH);
  delayMicroseconds(1);
  digitalWrite(PIN_LE, LOW);
}
