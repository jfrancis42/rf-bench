/*
 * SCPI IMU Controller for ESP32
 *
 * Reads MPU6050 6-axis IMU (accelerometer + gyroscope) via I2C
 * Provides SCPI access over TCP/IP
 *
 * Hardware connections:
 *   MPU6050 -> ESP32
 *     VCC -> 3.3V (or 5V if module has onboard regulator)
 *     GND -> GND
 *     SDA -> GPIO 21 (I2C SDA)
 *     SCL -> GPIO 22 (I2C SCL)
 *     AD0 -> GND (I2C address 0x68) or VCC (address 0x69)
 *
 * IMU provides:
 *   - 3-axis accelerometer (±2/4/8/16g configurable ranges)
 *   - 3-axis gyroscope (±250/500/1000/2000 °/s configurable ranges)
 *   - Die temperature sensor
 *   - Derived roll/pitch/yaw orientation from sensor fusion
 *
 * Install library: Adafruit MPU6050 (via Arduino Library Manager)
 * Also installs dependencies: Adafruit Unified Sensor, Adafruit BusIO
 */

#include <WiFi.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Wire.h>

// WiFi credentials - CHANGE THESE
const char* ssid = "YourSSID";
const char* password = "YourPassword";

// SCPI server port (standard is 5025)
const int scpi_port = 5025;

// I2C pins (ESP32 default)
const int i2c_sda = 21;
const int i2c_scl = 22;

// MPU6050 object
Adafruit_MPU6050 mpu;

// Current sensor configuration
mpu6050_accel_range_t accel_range = MPU6050_RANGE_2_G;
mpu6050_gyro_range_t gyro_range = MPU6050_RANGE_250_DEG;

// Complementary filter coefficient for orientation (0.0 - 1.0)
// Higher = trust gyro more, lower = trust accel more
// Typical: 0.96-0.98 for 100 Hz update rate
const float alpha = 0.96;

// Orientation state (roll, pitch, yaw in degrees)
// Roll = rotation about X axis (tilt left/right)
// Pitch = rotation about Y axis (tilt forward/back)
// Yaw = rotation about Z axis (compass heading)
float roll = 0.0;
float pitch = 0.0;
float yaw = 0.0;

// Last update time for gyro integration
unsigned long last_update = 0;

WiFiServer server(scpi_port);
WiFiClient client;

// Command buffer
char cmd_buffer[256];
int cmd_index = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n\nSCPI IMU Controller");
  Serial.println("===================");

  // Initialize I2C
  Wire.begin(i2c_sda, i2c_scl);
  Serial.printf("I2C: SDA=%d, SCL=%d\n", i2c_sda, i2c_scl);

  // Initialize MPU6050
  if (!mpu.begin()) {
    Serial.println("ERROR: MPU6050 not found!");
    Serial.println("Check wiring and I2C address (0x68 or 0x69)");
    while (1) {
      delay(1000);
    }
  }

  Serial.println("MPU6050 initialized");

  // Configure MPU6050 (defaults: 2g accel, 250°/s gyro, 100 Hz)
  mpu.setAccelerometerRange(accel_range);
  mpu.setGyroRange(gyro_range);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  Serial.printf("Accelerometer range: ±%dg\n", get_accel_range_value());
  Serial.printf("Gyroscope range: ±%d°/s\n", get_gyro_range_value());

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

  // Initialize orientation timestamp
  last_update = millis();
}

void loop() {
  // Update orientation at ~100 Hz
  update_orientation();

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

// Update orientation estimate using complementary filter
void update_orientation() {
  static unsigned long last_print = 0;

  // Read sensor data
  sensors_event_t accel, gyro, temp;
  mpu.getEvent(&accel, &gyro, &temp);

  // Calculate time delta (seconds)
  unsigned long now = millis();
  float dt = (now - last_update) / 1000.0;
  last_update = now;

  // Calculate roll and pitch from accelerometer (tilt sensing)
  // These are accurate when stationary but noisy during motion
  float accel_roll = atan2(accel.acceleration.y, accel.acceleration.z) * 180.0 / M_PI;
  float accel_pitch = atan2(-accel.acceleration.x,
                            sqrt(accel.acceleration.y * accel.acceleration.y +
                                 accel.acceleration.z * accel.acceleration.z)) * 180.0 / M_PI;

  // Integrate gyro rates to get orientation change
  // Gyro is accurate short-term but drifts over time
  float gyro_roll_rate = gyro.gyro.x * 180.0 / M_PI;   // rad/s to deg/s
  float gyro_pitch_rate = gyro.gyro.y * 180.0 / M_PI;
  float gyro_yaw_rate = gyro.gyro.z * 180.0 / M_PI;

  // Complementary filter: trust gyro short-term, correct with accel long-term
  roll = alpha * (roll + gyro_roll_rate * dt) + (1.0 - alpha) * accel_roll;
  pitch = alpha * (pitch + gyro_pitch_rate * dt) + (1.0 - alpha) * accel_pitch;

  // Yaw (compass heading) can only come from gyro integration
  // Without a magnetometer, yaw drifts over time (no absolute reference)
  yaw += gyro_yaw_rate * dt;

  // Wrap yaw to ±180°
  if (yaw > 180.0) yaw -= 360.0;
  if (yaw < -180.0) yaw += 360.0;

  // Debug output every second
  if (now - last_print > 1000) {
    Serial.printf("Roll: %6.2f  Pitch: %6.2f  Yaw: %6.2f\n", roll, pitch, yaw);
    last_print = now;
  }
}

// Get current accelerometer range value (in g)
int get_accel_range_value() {
  switch (accel_range) {
    case MPU6050_RANGE_2_G: return 2;
    case MPU6050_RANGE_4_G: return 4;
    case MPU6050_RANGE_8_G: return 8;
    case MPU6050_RANGE_16_G: return 16;
    default: return 2;
  }
}

// Get current gyroscope range value (in deg/s)
int get_gyro_range_value() {
  switch (gyro_range) {
    case MPU6050_RANGE_250_DEG: return 250;
    case MPU6050_RANGE_500_DEG: return 500;
    case MPU6050_RANGE_1000_DEG: return 1000;
    case MPU6050_RANGE_2000_DEG: return 2000;
    default: return 250;
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
    send_response("N0GQ,ESP32-SCPI-IMU,1.0,2026\n");
  }

  // *RST - Reset (zero orientation, reset to default ranges)
  else if (strcmp(cmd, "*RST") == 0) {
    roll = 0.0;
    pitch = 0.0;
    yaw = 0.0;
    accel_range = MPU6050_RANGE_2_G;
    gyro_range = MPU6050_RANGE_250_DEG;
    mpu.setAccelerometerRange(accel_range);
    mpu.setGyroRange(gyro_range);
    send_response("OK\n");
  }

  // SYST:ERR? - System error
  else if (strcmp(cmd, "SYST:ERR?") == 0 || strcmp(cmd, "SYSTEM:ERROR?") == 0) {
    send_response("0,\"No error\"\n");
  }

  // IMU:ACC? - Query acceleration (X,Y,Z in m/s²)
  else if (strcmp(cmd, "IMU:ACC?") == 0 || strcmp(cmd, "IMU:ACCELERATION?") == 0) {
    sensors_event_t accel, gyro, temp;
    mpu.getEvent(&accel, &gyro, &temp);
    snprintf(response, sizeof(response), "%.4f,%.4f,%.4f\n",
             accel.acceleration.x, accel.acceleration.y, accel.acceleration.z);
    send_response(response);
  }

  // IMU:GYRO? - Query rotation rate (X,Y,Z in °/s)
  else if (strcmp(cmd, "IMU:GYRO?") == 0 || strcmp(cmd, "IMU:GYROSCOPE?") == 0) {
    sensors_event_t accel, gyro, temp;
    mpu.getEvent(&accel, &gyro, &temp);
    // Convert rad/s to deg/s
    float gx = gyro.gyro.x * 180.0 / M_PI;
    float gy = gyro.gyro.y * 180.0 / M_PI;
    float gz = gyro.gyro.z * 180.0 / M_PI;
    snprintf(response, sizeof(response), "%.4f,%.4f,%.4f\n", gx, gy, gz);
    send_response(response);
  }

  // IMU:TEMP? - Query die temperature (°C)
  else if (strcmp(cmd, "IMU:TEMP?") == 0 || strcmp(cmd, "IMU:TEMPERATURE?") == 0) {
    sensors_event_t accel, gyro, temp;
    mpu.getEvent(&accel, &gyro, &temp);
    snprintf(response, sizeof(response), "%.2f\n", temp.temperature);
    send_response(response);
  }

  // IMU:ORIE? - Query orientation (roll,pitch,yaw in degrees)
  else if (strcmp(cmd, "IMU:ORIE?") == 0 || strcmp(cmd, "IMU:ORIENTATION?") == 0) {
    snprintf(response, sizeof(response), "%.2f,%.2f,%.2f\n", roll, pitch, yaw);
    send_response(response);
  }

  // IMU:ALL? - Query all data (9 values: ax,ay,az,gx,gy,gz,temp,roll,pitch,yaw)
  else if (strcmp(cmd, "IMU:ALL?") == 0) {
    sensors_event_t accel, gyro, temp;
    mpu.getEvent(&accel, &gyro, &temp);
    float gx = gyro.gyro.x * 180.0 / M_PI;
    float gy = gyro.gyro.y * 180.0 / M_PI;
    float gz = gyro.gyro.z * 180.0 / M_PI;
    snprintf(response, sizeof(response), "%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%.2f\n",
             accel.acceleration.x, accel.acceleration.y, accel.acceleration.z,
             gx, gy, gz,
             temp.temperature,
             roll, pitch, yaw);
    send_response(response);
  }

  // IMU:RANG:ACC,<range> - Set accelerometer range (2/4/8/16 g)
  else if (strncmp(cmd, "IMU:RANG:ACC", 12) == 0 || strncmp(cmd, "IMU:RANGE:ACCELEROMETER", 23) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int range;
      if (sscanf(comma + 1, "%d", &range) == 1) {
        switch (range) {
          case 2:
            accel_range = MPU6050_RANGE_2_G;
            mpu.setAccelerometerRange(accel_range);
            send_response("OK\n");
            break;
          case 4:
            accel_range = MPU6050_RANGE_4_G;
            mpu.setAccelerometerRange(accel_range);
            send_response("OK\n");
            break;
          case 8:
            accel_range = MPU6050_RANGE_8_G;
            mpu.setAccelerometerRange(accel_range);
            send_response("OK\n");
            break;
          case 16:
            accel_range = MPU6050_RANGE_16_G;
            mpu.setAccelerometerRange(accel_range);
            send_response("OK\n");
            break;
          default:
            send_response("ERROR: Invalid range (must be 2, 4, 8, or 16)\n");
            break;
        }
      } else {
        send_response("ERROR: Invalid range parameter\n");
      }
    } else {
      send_response("ERROR: Missing range parameter\n");
    }
  }

  // IMU:RANG:GYRO,<range> - Set gyroscope range (250/500/1000/2000 deg/s)
  else if (strncmp(cmd, "IMU:RANG:GYRO", 13) == 0 || strncmp(cmd, "IMU:RANGE:GYROSCOPE", 19) == 0) {
    const char* comma = strchr(cmd, ',');
    if (comma) {
      int range;
      if (sscanf(comma + 1, "%d", &range) == 1) {
        switch (range) {
          case 250:
            gyro_range = MPU6050_RANGE_250_DEG;
            mpu.setGyroRange(gyro_range);
            send_response("OK\n");
            break;
          case 500:
            gyro_range = MPU6050_RANGE_500_DEG;
            mpu.setGyroRange(gyro_range);
            send_response("OK\n");
            break;
          case 1000:
            gyro_range = MPU6050_RANGE_1000_DEG;
            mpu.setGyroRange(gyro_range);
            send_response("OK\n");
            break;
          case 2000:
            gyro_range = MPU6050_RANGE_2000_DEG;
            mpu.setGyroRange(gyro_range);
            send_response("OK\n");
            break;
          default:
            send_response("ERROR: Invalid range (must be 250, 500, 1000, or 2000)\n");
            break;
        }
      } else {
        send_response("ERROR: Invalid range parameter\n");
      }
    } else {
      send_response("ERROR: Missing range parameter\n");
    }
  }

  // IMU:RANG:ACC? - Query accelerometer range
  else if (strcmp(cmd, "IMU:RANG:ACC?") == 0 || strcmp(cmd, "IMU:RANGE:ACCELEROMETER?") == 0) {
    snprintf(response, sizeof(response), "%d\n", get_accel_range_value());
    send_response(response);
  }

  // IMU:RANG:GYRO? - Query gyroscope range
  else if (strcmp(cmd, "IMU:RANG:GYRO?") == 0 || strcmp(cmd, "IMU:RANGE:GYROSCOPE?") == 0) {
    snprintf(response, sizeof(response), "%d\n", get_gyro_range_value());
    send_response(response);
  }

  // Unknown command
  else {
    send_response("ERROR: Unknown command\n");
  }
}
