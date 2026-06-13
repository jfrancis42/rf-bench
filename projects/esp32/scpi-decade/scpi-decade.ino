/*
 * ESP32 SCPI Decade Box Controller
 *
 * Binary-weighted relay switching for resistance, capacitance, or inductance decades.
 * 10 relays provide decade steps via SCPI commands over USB serial.
 *
 * Hardware: 10 relays on GPIOs 25,26,27,14,32,33,23,19,18,5
 *
 * SCPI Commands:
 *   DEC:TYPE,<R|C|L>  — Set decade type (resistance/capacitance/inductance)
 *   DEC:TYPE?         — Query type
 *   DEC:VAL,<value>   — Set value (ohms/farads/henries)
 *   DEC:VAL?          — Query value
 *   DEC:STEP?         — Query step resolution
 *   DEC:MIN?          — Query minimum value
 *   DEC:MAX?          — Query maximum value
 *   *IDN?             — Identification string
 *   *RST              — Reset to default state
 */

// Relay GPIO assignments (binary-weighted)
const int RELAY_PINS[10] = {25, 26, 27, 14, 32, 33, 23, 19, 18, 5};
const int NUM_RELAYS = 10;

// Decade type
enum DecadeType {
  TYPE_RESISTANCE,
  TYPE_CAPACITANCE,
  TYPE_INDUCTANCE
};

DecadeType decadeType = TYPE_RESISTANCE;

// Current value and binary-weighted decade values
double currentValue = 0.0;

// Decade tables (binary-weighted powers of 10)
// For resistance: 1Ω base with binary weights
const double R_BASE_VALUES[10] = {
  1.0,        // 1Ω
  10.0,       // 10Ω
  100.0,      // 100Ω
  1000.0,     // 1kΩ
  10000.0,    // 10kΩ
  100000.0,   // 100kΩ
  1000000.0,  // 1MΩ
  10000000.0, // 10MΩ (optional)
  100000000.0,// 100MΩ (optional)
  1000000000.0// 1GΩ (optional)
};

// For capacitance: 1pF base with binary weights
const double C_BASE_VALUES[10] = {
  1e-12,      // 1pF
  10e-12,     // 10pF
  100e-12,    // 100pF
  1e-9,       // 1nF
  10e-9,      // 10nF
  100e-9,     // 100nF
  1e-6,       // 1µF
  10e-6,      // 10µF
  100e-6,     // 100µF
  1e-3        // 1mF
};

// For inductance: 1µH base with binary weights
const double L_BASE_VALUES[10] = {
  1e-6,       // 1µH
  10e-6,      // 10µH
  100e-6,     // 100µH
  1e-3,       // 1mH
  10e-3,      // 10mH
  100e-3,     // 100mH
  1.0,        // 1H
  10.0,       // 10H
  100.0,      // 100H
  1000.0      // 1kH
};

// Relay state (bit mask)
uint16_t relayState = 0;

void setup() {
  Serial.begin(115200);

  // Initialize relay pins as outputs, all OFF
  for (int i = 0; i < NUM_RELAYS; i++) {
    pinMode(RELAY_PINS[i], OUTPUT);
    digitalWrite(RELAY_PINS[i], LOW);
  }

  Serial.println("ESP32 SCPI Decade Box Ready");
  Serial.println("Type *IDN? for identification");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    processCommand(cmd);
  }
}

void processCommand(String cmd) {
  // *IDN? — Identification
  if (cmd == "*IDN?") {
    Serial.println("N0GQ,ESP32-SCPI-DECADE,001,1.0");
  }

  // *RST — Reset
  else if (cmd == "*RST") {
    resetDecadeBox();
    Serial.println("OK");
  }

  // DEC:TYPE? — Query type
  else if (cmd == "DEC:TYPE?") {
    if (decadeType == TYPE_RESISTANCE) {
      Serial.println("R");
    } else if (decadeType == TYPE_CAPACITANCE) {
      Serial.println("C");
    } else {
      Serial.println("L");
    }
  }

  // DEC:TYPE,<R|C|L> — Set type
  else if (cmd.startsWith("DEC:TYPE,")) {
    String type = cmd.substring(9);
    type.trim();
    if (type == "R") {
      decadeType = TYPE_RESISTANCE;
      resetDecadeBox();
      Serial.println("OK");
    } else if (type == "C") {
      decadeType = TYPE_CAPACITANCE;
      resetDecadeBox();
      Serial.println("OK");
    } else if (type == "L") {
      decadeType = TYPE_INDUCTANCE;
      resetDecadeBox();
      Serial.println("OK");
    } else {
      Serial.println("ERROR: Invalid type. Use R, C, or L");
    }
  }

  // DEC:VAL? — Query value
  else if (cmd == "DEC:VAL?") {
    Serial.println(currentValue, 12);
  }

  // DEC:VAL,<value> — Set value
  else if (cmd.startsWith("DEC:VAL,")) {
    String valStr = cmd.substring(8);
    valStr.trim();
    double value = valStr.toDouble();

    if (value < getMinValue() || value > getMaxValue()) {
      Serial.print("ERROR: Value out of range (");
      Serial.print(getMinValue(), 12);
      Serial.print(" to ");
      Serial.print(getMaxValue(), 12);
      Serial.println(")");
    } else {
      setValue(value);
      Serial.println("OK");
    }
  }

  // DEC:STEP? — Query step resolution
  else if (cmd == "DEC:STEP?") {
    Serial.println(getStepResolution(), 12);
  }

  // DEC:MIN? — Query minimum value
  else if (cmd == "DEC:MIN?") {
    Serial.println(getMinValue(), 12);
  }

  // DEC:MAX? — Query maximum value
  else if (cmd == "DEC:MAX?") {
    Serial.println(getMaxValue(), 12);
  }

  // Unknown command
  else {
    Serial.println("ERROR: Unknown command");
  }
}

void resetDecadeBox() {
  relayState = 0;
  currentValue = 0.0;
  updateRelays();
}

void setValue(double targetValue) {
  // Binary-weighted algorithm: find combination of relays that sum to target
  // Use a greedy approach: start from highest decade and work down

  const double* baseValues = getBaseValues();
  uint16_t newState = 0;
  double achievedValue = 0.0;

  // Start from highest relay and work down
  for (int i = NUM_RELAYS - 1; i >= 0; i--) {
    if (achievedValue + baseValues[i] <= targetValue + 1e-15) {  // Small epsilon for FP errors
      newState |= (1 << i);
      achievedValue += baseValues[i];
    }
  }

  relayState = newState;
  currentValue = achievedValue;
  updateRelays();
}

void updateRelays() {
  for (int i = 0; i < NUM_RELAYS; i++) {
    bool state = (relayState & (1 << i)) != 0;
    digitalWrite(RELAY_PINS[i], state ? HIGH : LOW);
  }
}

const double* getBaseValues() {
  switch (decadeType) {
    case TYPE_RESISTANCE:
      return R_BASE_VALUES;
    case TYPE_CAPACITANCE:
      return C_BASE_VALUES;
    case TYPE_INDUCTANCE:
      return L_BASE_VALUES;
    default:
      return R_BASE_VALUES;
  }
}

double getMinValue() {
  return getBaseValues()[0];
}

double getMaxValue() {
  const double* values = getBaseValues();
  double sum = 0.0;
  for (int i = 0; i < NUM_RELAYS; i++) {
    sum += values[i];
  }
  return sum;
}

double getStepResolution() {
  return getBaseValues()[0];  // Smallest step is the first relay value
}
