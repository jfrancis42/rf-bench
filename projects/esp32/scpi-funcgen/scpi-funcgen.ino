/*
 * ESP32 SCPI Function Generator
 *
 * Hardware: ESP32 internal 8-bit DAC on GPIO 25
 * Output: 0.1 Hz - 10 kHz, sine/square/triangle/sawtooth
 * Control: SCPI over Serial USB (115200 baud)
 *
 * SCPI Commands:
 *   FUNC,<SIN|SQU|TRI|SAW>   - Set waveform
 *   FUNC?                    - Query waveform
 *   FREQ,<hz>                - Set frequency (0.1 - 10000 Hz)
 *   FREQ?                    - Query frequency
 *   VOLT,<volts>             - Set amplitude pk-pk (0 - 3.3V)
 *   VOLT?                    - Query amplitude
 *   OFFS,<volts>             - Set DC offset (-1.65 - +1.65V)
 *   OFFS?                    - Query offset
 *   OUTP,<0|1>               - Disable/enable output
 *   OUTP?                    - Query output state
 *   *IDN?                    - Identify instrument
 *   *RST                     - Reset to defaults
 */

#include <driver/dac.h>

// Hardware config
#define DAC_PIN 25
#define DAC_CHANNEL DAC_CHANNEL_1  // GPIO 25 = DAC1

// DDS config
#define SAMPLE_RATE 50000          // 50 kHz update rate
#define TABLE_SIZE 256             // Waveform lookup table size
#define PHASE_BITS 32              // Phase accumulator width
#define PHASE_MAX 0xFFFFFFFF

// Waveform types
enum Waveform {
  WAVE_SINE = 0,
  WAVE_SQUARE,
  WAVE_TRIANGLE,
  WAVE_SAWTOOTH
};

// Generator state
struct GenState {
  Waveform waveform;
  float frequency;      // Hz
  float amplitude;      // Volts pk-pk
  float offset;         // Volts DC
  bool output_enabled;

  uint32_t phase_acc;   // DDS phase accumulator
  uint32_t phase_inc;   // Phase increment per sample
} gen = {
  WAVE_SINE,           // default waveform
  1000.0,              // default 1 kHz
  3.3,                 // default full-scale
  0.0,                 // default no offset
  false,               // default output off
  0,                   // phase accumulator starts at 0
  0                    // phase increment calculated in setup()
};

// 256-sample sine lookup table (0-255 range)
const uint8_t sine_table[TABLE_SIZE] = {
  128, 131, 134, 137, 140, 143, 146, 149, 152, 155, 158, 162, 165, 167, 170, 173,
  176, 179, 182, 185, 188, 190, 193, 196, 198, 201, 203, 206, 208, 211, 213, 215,
  218, 220, 222, 224, 226, 228, 230, 232, 234, 235, 237, 238, 240, 241, 243, 244,
  245, 246, 248, 249, 250, 250, 251, 252, 253, 253, 254, 254, 254, 255, 255, 255,
  255, 255, 255, 255, 254, 254, 254, 253, 253, 252, 251, 250, 250, 249, 248, 246,
  245, 244, 243, 241, 240, 238, 237, 235, 234, 232, 230, 228, 226, 224, 222, 220,
  218, 215, 213, 211, 208, 206, 203, 201, 198, 196, 193, 190, 188, 185, 182, 179,
  176, 173, 170, 167, 165, 162, 158, 155, 152, 149, 146, 143, 140, 137, 134, 131,
  128, 124, 121, 118, 115, 112, 109, 106, 103, 100,  97,  93,  90,  88,  85,  82,
   79,  76,  73,  70,  67,  65,  62,  59,  57,  54,  52,  49,  47,  44,  42,  40,
   37,  35,  33,  31,  29,  27,  25,  23,  21,  20,  18,  17,  15,  14,  12,  11,
   10,   9,   7,   6,   5,   5,   4,   3,   2,   2,   1,   1,   1,   0,   0,   0,
    0,   0,   0,   0,   1,   1,   1,   2,   2,   3,   4,   5,   5,   6,   7,   9,
   10,  11,  12,  14,  15,  17,  18,  20,  21,  23,  25,  27,  29,  31,  33,  35,
   37,  40,  42,  44,  47,  49,  52,  54,  57,  59,  62,  65,  67,  70,  73,  76,
   79,  82,  85,  88,  90,  93,  97, 100, 103, 106, 109, 112, 115, 118, 121, 124
};

// Timer for DDS updates
hw_timer_t *timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

// Generate sample based on current waveform and phase
uint8_t generate_sample(uint32_t phase) {
  uint8_t raw_value;
  uint8_t index = (phase >> (PHASE_BITS - 8)) & 0xFF;  // Top 8 bits = table index

  switch (gen.waveform) {
    case WAVE_SINE:
      raw_value = sine_table[index];
      break;

    case WAVE_SQUARE:
      raw_value = (phase & 0x80000000) ? 0 : 255;
      break;

    case WAVE_TRIANGLE:
      if (phase & 0x80000000) {
        // Falling edge
        raw_value = 255 - ((index * 2) & 0xFF);
      } else {
        // Rising edge
        raw_value = (index * 2) & 0xFF;
      }
      break;

    case WAVE_SAWTOOTH:
      raw_value = index;
      break;

    default:
      raw_value = 128;
  }

  // Apply amplitude scaling and offset
  // raw_value is 0-255, convert to -127 to +128
  int16_t signed_value = (int16_t)raw_value - 128;

  // Scale by amplitude (0-3.3V pk-pk -> 0.0-1.0 scaling)
  float scale = gen.amplitude / 3.3;
  signed_value = (int16_t)(signed_value * scale);

  // Apply offset (0-3.3V range, 1.65V center)
  float offset_dac = (gen.offset / 3.3) * 255.0;
  int16_t final_value = signed_value + 128 + (int16_t)offset_dac;

  // Clamp to 0-255
  if (final_value < 0) final_value = 0;
  if (final_value > 255) final_value = 255;

  return (uint8_t)final_value;
}

// Timer ISR - DDS update at SAMPLE_RATE Hz
void IRAM_ATTR onTimer() {
  portENTER_CRITICAL_ISR(&timerMux);

  if (gen.output_enabled) {
    uint8_t sample = generate_sample(gen.phase_acc);
    dac_output_voltage(DAC_CHANNEL, sample);
    gen.phase_acc += gen.phase_inc;
  } else {
    // Output disabled - center at offset
    float offset_dac = ((gen.offset / 3.3) * 255.0) + 128.0;
    int16_t value = (int16_t)offset_dac;
    if (value < 0) value = 0;
    if (value > 255) value = 255;
    dac_output_voltage(DAC_CHANNEL, (uint8_t)value);
  }

  portEXIT_CRITICAL_ISR(&timerMux);
}

// Calculate phase increment for given frequency
void update_phase_increment() {
  // phase_inc = (frequency * 2^32) / sample_rate
  gen.phase_inc = (uint32_t)((gen.frequency * (double)PHASE_MAX) / SAMPLE_RATE);
}

// SCPI command parser
String cmd_buffer = "";

void process_scpi_command(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  // Handle queries (ending with ?)
  if (cmd.endsWith("?")) {
    if (cmd == "*IDN?") {
      Serial.println("ESP32 SCPI Function Generator,v1.0,SN00001,FW1.0");
    }
    else if (cmd == "FUNC?") {
      switch (gen.waveform) {
        case WAVE_SINE: Serial.println("SIN"); break;
        case WAVE_SQUARE: Serial.println("SQU"); break;
        case WAVE_TRIANGLE: Serial.println("TRI"); break;
        case WAVE_SAWTOOTH: Serial.println("SAW"); break;
      }
    }
    else if (cmd == "FREQ?") {
      Serial.println(gen.frequency, 3);
    }
    else if (cmd == "VOLT?") {
      Serial.println(gen.amplitude, 3);
    }
    else if (cmd == "OFFS?") {
      Serial.println(gen.offset, 3);
    }
    else if (cmd == "OUTP?") {
      Serial.println(gen.output_enabled ? "1" : "0");
    }
    else {
      Serial.println("ERROR: Unknown query");
    }
    return;
  }

  // Handle set commands
  int comma_pos = cmd.indexOf(',');
  String command, param;

  if (comma_pos > 0) {
    command = cmd.substring(0, comma_pos);
    param = cmd.substring(comma_pos + 1);
    param.trim();
  } else {
    command = cmd;
  }

  if (command == "*RST") {
    gen.waveform = WAVE_SINE;
    gen.frequency = 1000.0;
    gen.amplitude = 3.3;
    gen.offset = 0.0;
    gen.output_enabled = false;
    gen.phase_acc = 0;
    update_phase_increment();
    Serial.println("OK");
  }
  else if (command == "FUNC") {
    if (param == "SIN") gen.waveform = WAVE_SINE;
    else if (param == "SQU") gen.waveform = WAVE_SQUARE;
    else if (param == "TRI") gen.waveform = WAVE_TRIANGLE;
    else if (param == "SAW") gen.waveform = WAVE_SAWTOOTH;
    else {
      Serial.println("ERROR: Invalid waveform");
      return;
    }
    Serial.println("OK");
  }
  else if (command == "FREQ") {
    float freq = param.toFloat();
    if (freq < 0.1 || freq > 10000.0) {
      Serial.println("ERROR: Frequency out of range (0.1 - 10000 Hz)");
      return;
    }
    gen.frequency = freq;
    update_phase_increment();
    Serial.println("OK");
  }
  else if (command == "VOLT") {
    float volt = param.toFloat();
    if (volt < 0.0 || volt > 3.3) {
      Serial.println("ERROR: Amplitude out of range (0 - 3.3V)");
      return;
    }
    gen.amplitude = volt;
    Serial.println("OK");
  }
  else if (command == "OFFS") {
    float offs = param.toFloat();
    if (offs < -1.65 || offs > 1.65) {
      Serial.println("ERROR: Offset out of range (-1.65 - +1.65V)");
      return;
    }
    gen.offset = offs;
    Serial.println("OK");
  }
  else if (command == "OUTP") {
    int state = param.toInt();
    if (state != 0 && state != 1) {
      Serial.println("ERROR: Output must be 0 or 1");
      return;
    }
    gen.output_enabled = (state == 1);
    if (!gen.output_enabled) {
      gen.phase_acc = 0;  // Reset phase when disabled
    }
    Serial.println("OK");
  }
  else {
    Serial.println("ERROR: Unknown command");
  }
}

void setup() {
  Serial.begin(115200);
  delay(100);

  // Initialize DAC
  dac_output_enable(DAC_CHANNEL);
  dac_output_voltage(DAC_CHANNEL, 128);  // Start at mid-scale

  // Calculate initial phase increment
  update_phase_increment();

  // Setup timer for DDS updates
  timer = timerBegin(0, 80, true);  // Timer 0, prescaler 80 (1 MHz clock)
  timerAttachInterrupt(timer, &onTimer, true);
  timerAlarmWrite(timer, 1000000 / SAMPLE_RATE, true);  // Alarm every 1/SAMPLE_RATE seconds
  timerAlarmEnable(timer);

  Serial.println("");
  Serial.println("ESP32 SCPI Function Generator Ready");
  Serial.println("Commands: FUNC, FREQ, VOLT, OFFS, OUTP (append ? to query)");
  Serial.println("Example: FUNC,SIN or FREQ,440 or OUTP,1");
}

void loop() {
  // Process serial input
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (cmd_buffer.length() > 0) {
        process_scpi_command(cmd_buffer);
        cmd_buffer = "";
      }
    } else {
      cmd_buffer += c;
    }
  }

  // Non-blocking main loop - all work done in timer ISR
  delay(1);
}
