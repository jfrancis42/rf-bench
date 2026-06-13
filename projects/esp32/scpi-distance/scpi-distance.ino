/**
 * ESP32 SCPI Distance Sensor
 *
 * HC-SR04 ultrasonic distance sensor with SCPI interface over USB serial.
 *
 * Hardware:
 *   - HC-SR04 TRIG: GPIO 25
 *   - HC-SR04 ECHO: GPIO 26
 *   - Range: 2-400 cm (±3mm accuracy)
 *
 * SCPI Commands:
 *   DIST:MEAS?              - Single distance measurement (returns in current unit)
 *   DIST:CONT?              - 10-sample averaged measurement (returns in current unit)
 *   DIST:UNIT,<MM|CM|IN>    - Set distance unit
 *   DIST:UNIT?              - Query current unit
 *   DIST:ALAR:HIGH,<mm>     - Set high alarm threshold (in mm)
 *   DIST:ALAR:LOW,<mm>      - Set low alarm threshold (in mm)
 *   DIST:ALAR?              - Query alarm state (0=OK, 1=LOW, 2=HIGH)
 *   *IDN?                   - Query identification
 *   *RST                    - Reset to defaults
 *
 * Author: JF8Call / N0GQ
 * License: MIT
 */

#include <Arduino.h>

// Pin definitions
#define TRIG_PIN 25
#define ECHO_PIN 26

// Timing constants (HC-SR04 datasheet)
#define TRIG_PULSE_US 10
#define MAX_ECHO_TIMEOUT_US 25000  // ~4.3m max range at 343 m/s

// Distance calculation constants
#define SOUND_SPEED_CM_PER_US 0.0343  // Speed of sound at 20°C: 343 m/s
#define INVALID_DISTANCE -1.0

// Unit enumeration
enum Unit {
  UNIT_MM = 0,
  UNIT_CM = 1,
  UNIT_IN = 2
};

// Global state
Unit currentUnit = UNIT_MM;
float alarmLow = 0.0;      // Low alarm threshold (mm)
float alarmHigh = 10000.0; // High alarm threshold (mm)

// Command buffer
#define CMD_BUFFER_SIZE 128
char cmdBuffer[CMD_BUFFER_SIZE];
int cmdIndex = 0;

/**
 * Measure distance in millimeters using HC-SR04
 * Returns INVALID_DISTANCE on timeout or out-of-range
 */
float measureDistanceMM() {
  // Send trigger pulse
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(TRIG_PULSE_US);
  digitalWrite(TRIG_PIN, LOW);

  // Wait for echo pulse and measure duration
  long duration = pulseIn(ECHO_PIN, HIGH, MAX_ECHO_TIMEOUT_US);

  if (duration == 0) {
    // Timeout - no echo received
    return INVALID_DISTANCE;
  }

  // Calculate distance: duration (us) * speed (cm/us) / 2 (round trip) * 10 (cm to mm)
  float distanceMM = (duration * SOUND_SPEED_CM_PER_US / 2.0) * 10.0;

  // Validate range (20mm to 4000mm as per HC-SR04 specs)
  if (distanceMM < 20.0 || distanceMM > 4000.0) {
    return INVALID_DISTANCE;
  }

  return distanceMM;
}

/**
 * Measure distance with averaging (10 samples)
 * Outlier rejection: discard measurements > 2σ from mean
 */
float measureDistanceAveraged() {
  const int numSamples = 10;
  float samples[numSamples];
  int validCount = 0;

  // Collect samples
  for (int i = 0; i < numSamples; i++) {
    float dist = measureDistanceMM();
    if (dist != INVALID_DISTANCE) {
      samples[validCount++] = dist;
    }
    delay(60); // HC-SR04 needs ~50ms between measurements
  }

  if (validCount == 0) {
    return INVALID_DISTANCE;
  }

  // Calculate mean
  float sum = 0.0;
  for (int i = 0; i < validCount; i++) {
    sum += samples[i];
  }
  float mean = sum / validCount;

  // Calculate standard deviation
  float variance = 0.0;
  for (int i = 0; i < validCount; i++) {
    float diff = samples[i] - mean;
    variance += diff * diff;
  }
  float stdDev = sqrt(variance / validCount);

  // Re-average without outliers (> 2σ from mean)
  sum = 0.0;
  int finalCount = 0;
  for (int i = 0; i < validCount; i++) {
    if (abs(samples[i] - mean) <= 2.0 * stdDev) {
      sum += samples[i];
      finalCount++;
    }
  }

  if (finalCount == 0) {
    return mean; // All were outliers; return original mean
  }

  return sum / finalCount;
}

/**
 * Convert distance from mm to current unit
 */
float convertDistance(float distMM) {
  switch (currentUnit) {
    case UNIT_MM:
      return distMM;
    case UNIT_CM:
      return distMM / 10.0;
    case UNIT_IN:
      return distMM / 25.4;
    default:
      return distMM;
  }
}

/**
 * Get current unit string
 */
const char* getUnitString() {
  switch (currentUnit) {
    case UNIT_MM: return "MM";
    case UNIT_CM: return "CM";
    case UNIT_IN: return "IN";
    default: return "MM";
  }
}

/**
 * Check if distance triggers alarm
 * Returns: 0=OK, 1=LOW, 2=HIGH
 */
int checkAlarm(float distMM) {
  if (distMM < alarmLow) return 1;
  if (distMM > alarmHigh) return 2;
  return 0;
}

/**
 * Parse and execute SCPI command
 */
void processCommand(const char* cmd) {
  // Convert to uppercase for case-insensitive matching
  String cmdStr = String(cmd);
  cmdStr.toUpperCase();
  cmdStr.trim();

  // *IDN?
  if (cmdStr.equals("*IDN?")) {
    Serial.println("N0GQ,ESP32-SCPI-DISTANCE,HC-SR04,v1.0");
    return;
  }

  // *RST
  if (cmdStr.equals("*RST")) {
    currentUnit = UNIT_MM;
    alarmLow = 0.0;
    alarmHigh = 10000.0;
    Serial.println("OK");
    return;
  }

  // DIST:MEAS?
  if (cmdStr.equals("DIST:MEAS?")) {
    float distMM = measureDistanceMM();
    if (distMM == INVALID_DISTANCE) {
      Serial.println("ERROR: OUT OF RANGE");
    } else {
      float converted = convertDistance(distMM);
      Serial.print(converted, 2);
      Serial.print(" ");
      Serial.println(getUnitString());
    }
    return;
  }

  // DIST:CONT?
  if (cmdStr.equals("DIST:CONT?")) {
    float distMM = measureDistanceAveraged();
    if (distMM == INVALID_DISTANCE) {
      Serial.println("ERROR: OUT OF RANGE");
    } else {
      float converted = convertDistance(distMM);
      Serial.print(converted, 2);
      Serial.print(" ");
      Serial.println(getUnitString());
    }
    return;
  }

  // DIST:UNIT?
  if (cmdStr.equals("DIST:UNIT?")) {
    Serial.println(getUnitString());
    return;
  }

  // DIST:UNIT,<unit>
  if (cmdStr.startsWith("DIST:UNIT,")) {
    String unitStr = cmdStr.substring(10);
    unitStr.trim();
    if (unitStr.equals("MM")) {
      currentUnit = UNIT_MM;
      Serial.println("OK");
    } else if (unitStr.equals("CM")) {
      currentUnit = UNIT_CM;
      Serial.println("OK");
    } else if (unitStr.equals("IN")) {
      currentUnit = UNIT_IN;
      Serial.println("OK");
    } else {
      Serial.println("ERROR: INVALID UNIT (use MM, CM, or IN)");
    }
    return;
  }

  // DIST:ALAR:HIGH,<mm>
  if (cmdStr.startsWith("DIST:ALAR:HIGH,")) {
    String valueStr = cmdStr.substring(15);
    valueStr.trim();
    float value = valueStr.toFloat();
    if (value > 0.0 && value <= 10000.0) {
      alarmHigh = value;
      Serial.println("OK");
    } else {
      Serial.println("ERROR: VALUE OUT OF RANGE (0-10000 mm)");
    }
    return;
  }

  // DIST:ALAR:LOW,<mm>
  if (cmdStr.startsWith("DIST:ALAR:LOW,")) {
    String valueStr = cmdStr.substring(14);
    valueStr.trim();
    float value = valueStr.toFloat();
    if (value >= 0.0 && value < 10000.0) {
      alarmLow = value;
      Serial.println("OK");
    } else {
      Serial.println("ERROR: VALUE OUT OF RANGE (0-10000 mm)");
    }
    return;
  }

  // DIST:ALAR?
  if (cmdStr.equals("DIST:ALAR?")) {
    float distMM = measureDistanceMM();
    if (distMM == INVALID_DISTANCE) {
      Serial.println("ERROR: OUT OF RANGE");
    } else {
      int alarmState = checkAlarm(distMM);
      Serial.println(alarmState);
    }
    return;
  }

  // Unknown command
  Serial.println("ERROR: UNKNOWN COMMAND");
}

void setup() {
  // Initialize serial port
  Serial.begin(115200);
  while (!Serial) {
    ; // Wait for USB serial to connect
  }

  // Initialize HC-SR04 pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  // Startup message
  delay(100);
  Serial.println();
  Serial.println("ESP32 SCPI Distance Sensor v1.0");
  Serial.println("HC-SR04 on TRIG=GPIO25, ECHO=GPIO26");
  Serial.println("Ready for commands. Type *IDN? for identification.");
  Serial.println();
}

void loop() {
  // Read incoming serial data
  while (Serial.available() > 0) {
    char c = Serial.read();

    // Line terminator (LF, CR, or semicolon)
    if (c == '\n' || c == '\r' || c == ';') {
      if (cmdIndex > 0) {
        cmdBuffer[cmdIndex] = '\0';
        processCommand(cmdBuffer);
        cmdIndex = 0;
      }
    }
    // Printable character
    else if (c >= 32 && c <= 126) {
      if (cmdIndex < CMD_BUFFER_SIZE - 1) {
        cmdBuffer[cmdIndex++] = c;
      } else {
        // Buffer overflow - reset
        Serial.println("ERROR: COMMAND TOO LONG");
        cmdIndex = 0;
      }
    }
  }

  // Small delay to avoid hammering the serial port
  delay(1);
}
