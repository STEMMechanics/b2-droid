#include <LedControl.h>
#include <Wire.h>

// LED matrix: DIN, CLK, CS, number of devices.
LedControl matrix(11, 13, 10, 1);

// L298N direction inputs.
const byte LEFT_IN1 = 5;
const byte LEFT_IN2 = 6;
const byte RIGHT_IN3 = 7;
const byte RIGHT_IN4 = 8;

// Remove the L298N ENA/ENB jumpers and wire ENA->D3 and ENB->D9 for
// controllable wheel speed. Set false only when retaining the jumpers.
const bool USE_PWM_ENABLE = true;
const byte LEFT_ENABLE = 3;
const byte RIGHT_ENABLE = 9;
byte motorSpeed = 110;  // 0..255; adjustable over serial with speed:NN.

// Moving commands must be refreshed at least once per second.
const unsigned long MOTOR_WATCHDOG_MS = 1000;
const unsigned long HOST_WATCHDOG_MS = 8000;
const unsigned long UPDATE_WATCHDOG_MS = 900000;
unsigned long lastMotorCommand = 0;
unsigned long lastHostCommand = 0;
bool motorsMoving = false;

// Runtime hardware is intentionally volatile. Python's SQLite registry is the
// source of truth and reprovisions this table after every connection.
const byte MAX_DYNAMIC_DEVICES = 12;
enum HardwareType { HW_NONE, HW_ULTRASONIC, HW_IR_DISTANCE, HW_HALL, HW_COMPASS,
                    HW_MCP23008, HW_L298N, HW_SERVO, HW_PCA9685 };
struct DynamicDevice {
  bool used;
  String name;
  HardwareType type;
  int pin1;
  int pin2;
  byte address;
  unsigned long pulses;
  int lastInput;
};
DynamicDevice dynamicDevices[MAX_DYNAMIC_DEVICES];

int protocolPin(String value) {
  value.toUpperCase();
  if (value.length() == 2 && value.charAt(0) == 'A' && isDigit(value.charAt(1))) {
    int index = value.substring(1).toInt();
    return index <= 5 ? A0 + index : -1;
  }
  if (value.length() >= 2 && value.charAt(0) == 'D') {
    int pin = value.substring(1).toInt();
    return pin >= 0 && pin <= 13 ? pin : -1;
  }
  // Expander/controller resources are validated and owned by their parent.
  if (value.indexOf(":GP") > 0 || value.indexOf(":CH") > 0) return -2;
  return -1;
}

HardwareType hardwareType(String name) {
  if (name == "ultrasonic") return HW_ULTRASONIC;
  if (name == "ir_distance") return HW_IR_DISTANCE;
  if (name == "hall_sensor") return HW_HALL;
  if (name == "compass") return HW_COMPASS;
  if (name == "mcp23008") return HW_MCP23008;
  if (name == "l298n") return HW_L298N;
  if (name == "servo") return HW_SERVO;
  if (name == "pca9685") return HW_PCA9685;
  return HW_NONE;
}

DynamicDevice* findDynamicDevice(String name) {
  for (byte i = 0; i < MAX_DYNAMIC_DEVICES; i++) {
    if (dynamicDevices[i].used && dynamicDevices[i].name == name) return &dynamicDevices[i];
  }
  return NULL;
}

void resetDynamicHardware() {
  for (byte i = 0; i < MAX_DYNAMIC_DEVICES; i++) {
    if (dynamicDevices[i].used && dynamicDevices[i].pin1 >= 0) {
      pinMode(dynamicDevices[i].pin1, INPUT);
    }
    if (dynamicDevices[i].used && dynamicDevices[i].pin2 >= 0) {
      pinMode(dynamicDevices[i].pin2, INPUT);
    }
    dynamicDevices[i].used = false;
    dynamicDevices[i].name = "";
  }
}

void acknowledgeError(String code, String message) {
  Serial.print("ERR:"); Serial.print(code); Serial.print(":"); Serial.println(message);
}

void addDynamicHardware(String body) {
  int split = body.indexOf(':');
  if (split <= 0) { acknowledgeError("MALFORMED", "missing device type"); return; }
  String name = body.substring(0, split);
  body = body.substring(split + 1);
  split = body.indexOf(':');
  String typeName = split < 0 ? body : body.substring(0, split);
  String fields = split < 0 ? "" : body.substring(split + 1);
  HardwareType type = hardwareType(typeName);
  if (type == HW_NONE || findDynamicDevice(name) != NULL) {
    acknowledgeError("INVALID_DEVICE", "unsupported or duplicate device"); return;
  }
  DynamicDevice* device = NULL;
  for (byte i = 0; i < MAX_DYNAMIC_DEVICES; i++) {
    if (!dynamicDevices[i].used) { device = &dynamicDevices[i]; break; }
  }
  if (device == NULL) { acknowledgeError("FULL", "dynamic device table full"); return; }
  device->used = true; device->name = name; device->type = type;
  device->pin1 = -1; device->pin2 = -1; device->address = 0; device->pulses = 0;
  while (fields.length()) {
    int next = fields.indexOf(':');
    String field = next < 0 ? fields : fields.substring(0, next);
    fields = next < 0 ? "" : fields.substring(next + 1);
    int equals = field.indexOf('=');
    if (equals < 1) continue;
    String key = field.substring(0, equals);
    String value = field.substring(equals + 1);
    int pin = protocolPin(value);
    if (key == "trigger" || key == "analogue" || key == "input" || key == "signal" || key == "in1") device->pin1 = pin;
    else if (key == "echo" || key == "in2") device->pin2 = pin;
    else if (key == "address") device->address = (byte)strtol(value.c_str(), NULL, 0);
  }
  if (type == HW_ULTRASONIC) { pinMode(device->pin1, OUTPUT); digitalWrite(device->pin1, LOW); pinMode(device->pin2, INPUT); }
  else if (type == HW_IR_DISTANCE || type == HW_HALL) { pinMode(device->pin1, INPUT); device->lastInput = digitalRead(device->pin1); }
  Serial.print("ACK:ADD:"); Serial.println(name);
}

void readDynamicHardware(String name, bool testing) {
  DynamicDevice* device = findDynamicDevice(name);
  if (device == NULL) { acknowledgeError("NOT_FOUND", name); return; }
  if (device->type == HW_ULTRASONIC) {
    digitalWrite(device->pin1, LOW); delayMicroseconds(2);
    digitalWrite(device->pin1, HIGH); delayMicroseconds(10); digitalWrite(device->pin1, LOW);
    unsigned long duration = pulseIn(device->pin2, HIGH, 30000UL);
    if (duration == 0) { Serial.print("DEVICE:"); Serial.print(name); Serial.println(":UNAVAILABLE"); }
    else { Serial.print("READ:"); Serial.print(name); Serial.print(":CM:"); Serial.println(duration * 0.0343 / 2.0, 1); }
  } else if (device->type == HW_IR_DISTANCE) {
    Serial.print("READ:"); Serial.print(name); Serial.print(":ADC:"); Serial.println(analogRead(device->pin1));
  } else if (device->type == HW_HALL) {
    Serial.print("READ:"); Serial.print(name); Serial.print(":PULSES:"); Serial.println(device->pulses);
  } else if (device->type == HW_COMPASS || device->type == HW_MCP23008 || device->type == HW_PCA9685) {
    Wire.beginTransmission(device->address);
    byte error = Wire.endTransmission();
    Serial.print("DEVICE:"); Serial.print(name); Serial.println(error == 0 ? ":OK" : ":UNAVAILABLE");
  } else {
    // Configuration presence can be verified without actuating motors/servos.
    Serial.print("DEVICE:"); Serial.print(name); Serial.println(":UNVERIFIED");
  }
  Serial.println("ACK");
}

void handleHardwareCommand(String command) {
  if (command == "HW:RESET") { stopMotors(); resetDynamicHardware(); Serial.println("ACK:RESET"); return; }
  if (command == "HW:I2C_SCAN") {
    for (byte address = 8; address <= 0x77; address++) {
      Wire.beginTransmission(address);
      if (Wire.endTransmission() == 0) { Serial.print("I2C:0x"); if (address < 16) Serial.print('0'); Serial.println(address, HEX); }
    }
    Serial.println("ACK:SCAN"); return;
  }
  if (command.startsWith("HW:ADD:")) { addDynamicHardware(command.substring(7)); return; }
  if (command.startsWith("HW:REMOVE:")) {
    DynamicDevice* device = findDynamicDevice(command.substring(10));
    if (device == NULL) acknowledgeError("NOT_FOUND", command.substring(10));
    else { device->used = false; device->name = ""; Serial.println("ACK:REMOVE"); }
    return;
  }
  if (command.startsWith("HW:READ:")) { readDynamicHardware(command.substring(8), false); return; }
  if (command.startsWith("HW:TEST:")) { readDynamicHardware(command.substring(8), true); return; }
  if (command == "HW:LIST") {
    for (byte i = 0; i < MAX_DYNAMIC_DEVICES; i++) if (dynamicDevices[i].used) {
      Serial.print("DEVICE:"); Serial.print(dynamicDevices[i].name); Serial.println(":UNVERIFIED");
    }
    Serial.println("ACK:LIST"); return;
  }
  acknowledgeError("UNKNOWN_COMMAND", command);
}

byte happy[8] = {
  B00000000,
  B01100110,
  B01100110,
  B00000000,
  B00000000,
  B01000010,
  B00111100,
  B00000000
};

byte thinking[8] = {
  B00000000,
  B01100110,
  B00100100,
  B00000000,
  B00011000,
  B00001000,
  B00010000,
  B00000000
};

byte asleep[8] = {
  B00000000,
  B00000000,
  B01100110,
  B00000000,
  B00000000,
  B00111100,
  B00000000,
  B00000000
};

byte blinkFace[8] = {
  B00000000,
  B00000000,
  B01100110,
  B00000000,
  B00000000,
  B01000010,
  B00111100,
  B00000000
};

byte talk1[8] = {
  B00000000,
  B01100110,
  B01100110,
  B00000000,
  B00000000,
  B00111100,
  B00111100,
  B00000000
};

byte talk2[8] = {
  B00000000,
  B01100110,
  B01100110,
  B00000000,
  B00000000,
  B00011000,
  B00011000,
  B00000000
};

byte talk3[8] = {
  B00000000,
  B01100110,
  B01100110,
  B00000000,
  B00000000,
  B01111110,
  B00000000,
  B00000000
};

byte listen1[8] = {
  B00000000,
  B01100110,
  B01100110,
  B00000000,
  B00000000,
  B00011000,
  B00000000,
  B00000000
};

byte listen2[8] = {
  B00000000,
  B11100111,
  B11100111,
  B00000000,
  B00000000,
  B00011000,
  B00000000,
  B00000000
};

byte curious[8] = {
  B00000000, B01100000, B00000110, B00000000,
  B00011000, B00000100, B00011000, B00000000
};

byte waitingFace[8] = {
  B00000000, B00100100, B00100100, B00000000,
  B00000000, B00111100, B00000000, B00000000
};

byte errorFace[8] = {
  B00000000, B01000010, B00100100, B00000000,
  B00000000, B00111100, B01000010, B00000000
};

byte lonelyFace[8] = {
  B00000000, B00000000, B00100100, B00000000,
  B00000000, B00011000, B00100100, B00000000
};

byte excitedFace[8] = {
  B00000000, B11100111, B10100101, B00000000,
  B01000010, B00111100, B00000000, B00000000
};

byte concernedFace[8] = {
  B00000000, B01100010, B00100110, B00000000,
  B00000000, B00111100, B01000010, B00000000
};

byte boot1[8] = {
  B00011000, B00100100, B01000010, B10000001,
  B10000000, B01000000, B00100000, B00010000
};

byte boot2[8] = {
  B00001000, B00000100, B00000010, B00000001,
  B10000001, B01000010, B00100100, B00011000
};

byte boot3[8] = {
  B00010000, B00100000, B01000000, B10000000,
  B10000001, B01000010, B00100100, B00011000
};

// A downward package arrow, deliberately distinct from the rotating boot ring.
byte updating1[8] = {
  B00011000, B00011000, B00011000, B01111110,
  B00111100, B00011000, B00000000, B11111111
};

byte updating2[8] = {
  B00000000, B00011000, B00011000, B00011000,
  B01111110, B00111100, B00011000, B11111111
};

byte customFrame[8] = {
  B00000000, B00000000, B00000000, B00000000,
  B00000000, B00000000, B00000000, B00000000
};

byte offlineDot[8] = {
  B00000000, B00000000, B00000000, B00000000,
  B00000000, B00000000, B00000000, B00000001
};

byte blankFace[8] = {
  B00000000, B00000000, B00000000, B00000000,
  B00000000, B00000000, B00000000, B00000000
};

enum State {
  IDLE,
  LISTENING,
  THINKING,
  TALKING,
  SLEEPING,
  CURIOUS,
  WAITING,
  ERROR_STATE,
  LONELY,
  EXCITED,
  CONCERNED,
  BOOTING,
  UPDATING,
  CUSTOM,
  OFFLINE
};

State state = IDLE;

unsigned long nextBlink = 0;
bool blinking = false;
unsigned long blinkEnd = 0;

unsigned long nextTalkFrame = 0;
int talkFrame = 0;

unsigned long nextListenFrame = 0;
bool listenFrame = false;

unsigned long nextBootFrame = 0;
byte bootFrame = 0;
unsigned long nextUpdateFrame = 0;
bool updateFrame = false;
unsigned long nextOfflineFrame = 0;
bool offlineDotVisible = true;

void showFace(byte face[]) {
  for (int row = 0; row < 8; row++) {
    matrix.setRow(0, row, face[row]);
  }
}

void setState(State newState) {
  state = newState;
  blinking = false;

  switch (state) {
    case IDLE:
      showFace(happy);
      nextBlink = millis() + random(2000, 6000);
      break;

    case LISTENING:
      listenFrame = false;
      showFace(listen1);
      nextListenFrame = millis() + 350;
      break;

    case THINKING:
      showFace(thinking);
      break;

    case TALKING:
      talkFrame = 0;
      showFace(talk1);
      nextTalkFrame = millis() + 120;
      break;

    case SLEEPING:
      showFace(asleep);
      break;

    case CURIOUS:
      showFace(curious);
      break;

    case WAITING:
      showFace(waitingFace);
      break;

    case ERROR_STATE:
      showFace(errorFace);
      break;

    case LONELY:
      showFace(lonelyFace);
      break;

    case EXCITED:
      showFace(excitedFace);
      break;

    case CONCERNED:
      showFace(concernedFace);
      break;

    case BOOTING:
      bootFrame = 0;
      showFace(boot1);
      nextBootFrame = millis() + 140;
      break;

    case UPDATING:
      stopMotors();
      updateFrame = false;
      showFace(updating1);
      nextUpdateFrame = millis() + 450;
      break;

    case CUSTOM:
      showFace(customFrame);
      break;

    case OFFLINE:
      offlineDotVisible = true;
      showFace(offlineDot);
      nextOfflineFrame = millis() + 700;
      break;
  }
}

void stopMotors() {
  if (USE_PWM_ENABLE) {
    analogWrite(LEFT_ENABLE, 0);
    analogWrite(RIGHT_ENABLE, 0);
  }
  digitalWrite(LEFT_IN1, LOW);
  digitalWrite(LEFT_IN2, LOW);
  digitalWrite(RIGHT_IN3, LOW);
  digitalWrite(RIGHT_IN4, LOW);
  motorsMoving = false;
}

void enableMotors() {
  if (USE_PWM_ENABLE) {
    analogWrite(LEFT_ENABLE, motorSpeed);
    analogWrite(RIGHT_ENABLE, motorSpeed);
  }
}

void driveForward() {
  digitalWrite(LEFT_IN1, HIGH);
  digitalWrite(LEFT_IN2, LOW);
  digitalWrite(RIGHT_IN3, HIGH);
  digitalWrite(RIGHT_IN4, LOW);
  enableMotors();
  lastMotorCommand = millis();
  motorsMoving = true;
}

void driveReverse() {
  digitalWrite(LEFT_IN1, LOW);
  digitalWrite(LEFT_IN2, HIGH);
  digitalWrite(RIGHT_IN3, LOW);
  digitalWrite(RIGHT_IN4, HIGH);
  enableMotors();
  lastMotorCommand = millis();
  motorsMoving = true;
}

void turnLeft() {
  digitalWrite(LEFT_IN1, LOW);
  digitalWrite(LEFT_IN2, HIGH);
  digitalWrite(RIGHT_IN3, HIGH);
  digitalWrite(RIGHT_IN4, LOW);
  enableMotors();
  lastMotorCommand = millis();
  motorsMoving = true;
}

void turnRight() {
  digitalWrite(LEFT_IN1, HIGH);
  digitalWrite(LEFT_IN2, LOW);
  digitalWrite(RIGHT_IN3, LOW);
  digitalWrite(RIGHT_IN4, HIGH);
  enableMotors();
  lastMotorCommand = millis();
  motorsMoving = true;
}

void readCommands() {
  if (!Serial.available()) return;

  String command = Serial.readStringUntil('\n');
  command.trim();
  if (command.length() == 0) return;
  lastHostCommand = millis();

  if (command.startsWith("HW:")) { handleHardwareCommand(command); return; }

  if (command == "idle") setState(IDLE);
  else if (command == "listening") setState(LISTENING);
  else if (command == "thinking") setState(THINKING);
  else if (command == "talking") setState(TALKING);
  else if (command == "sleep") setState(SLEEPING);
  else if (command == "curious") setState(CURIOUS);
  else if (command == "waiting") setState(WAITING);
  else if (command == "error") setState(ERROR_STATE);
  else if (command == "lonely") setState(LONELY);
  else if (command == "excited") setState(EXCITED);
  else if (command == "concerned") setState(CONCERNED);
  else if (command == "booting") setState(BOOTING);
  else if (command == "updating") setState(UPDATING);
  else if (command == "offline") setState(OFFLINE);
  else if (command == "heartbeat") { /* Host-alive marker only. */ }
  else if (command.startsWith("speed:")) {
    int requested = command.substring(6).toInt();
    motorSpeed = constrain(requested, 0, 255);
    Serial.print("speed:");
    Serial.println(motorSpeed);
  }
  else if (command.startsWith("matrix:") && command.length() == 23) {
    bool valid = true;
    for (byte row = 0; row < 8; row++) {
      char high = command.charAt(7 + row * 2);
      char low = command.charAt(8 + row * 2);
      int highValue = isDigit(high) ? high - '0' :
        (high >= 'a' && high <= 'f' ? high - 'a' + 10 : -1);
      int lowValue = isDigit(low) ? low - '0' :
        (low >= 'a' && low <= 'f' ? low - 'a' + 10 : -1);
      if (highValue < 0 || lowValue < 0) {
        valid = false;
        break;
      }
      customFrame[row] = (byte)((highValue << 4) | lowValue);
    }
    if (valid) setState(CUSTOM);
  }
  else if (command == "forward") driveForward();
  else if (command == "reverse") driveReverse();
  else if (command == "left") turnLeft();
  else if (command == "right") turnRight();
  else if (command == "stop") stopMotors();
}

void updateHostWatchdog() {
  unsigned long timeout = state == UPDATING ? UPDATE_WATCHDOG_MS : HOST_WATCHDOG_MS;
  if (state != OFFLINE && millis() - lastHostCommand >= timeout) {
    stopMotors();
    setState(OFFLINE);
  }
}

void updateUpdatingAnimation() {
  if (state != UPDATING) return;
  unsigned long now = millis();
  if (now < nextUpdateFrame) return;
  updateFrame = !updateFrame;
  showFace(updateFrame ? updating2 : updating1);
  nextUpdateFrame = now + 450;
}

void updateOfflineAnimation() {
  if (state != OFFLINE) return;
  unsigned long now = millis();
  if (now < nextOfflineFrame) return;
  offlineDotVisible = !offlineDotVisible;
  showFace(offlineDotVisible ? offlineDot : blankFace);
  nextOfflineFrame = now + 700;
}

void updateMotorWatchdog() {
  if (
    motorsMoving
    && millis() - lastMotorCommand >= MOTOR_WATCHDOG_MS
  ) {
    stopMotors();
  }
}

void updateIdleAnimation() {
  if (state != IDLE) return;

  unsigned long now = millis();

  if (!blinking && now >= nextBlink) {
    showFace(blinkFace);
    blinking = true;
    blinkEnd = now + 150;
  }

  if (blinking && now >= blinkEnd) {
    showFace(happy);
    blinking = false;
    nextBlink = now + random(2000, 6000);
  }
}

void updateTalkingAnimation() {
  if (state != TALKING) return;

  unsigned long now = millis();
  if (now < nextTalkFrame) return;

  nextTalkFrame = now + random(90, 220);
  talkFrame = random(0, 3);

  switch (talkFrame) {
    case 0:
      showFace(talk1);
      break;
    case 1:
      showFace(talk2);
      break;
    case 2:
      showFace(talk3);
      break;
  }
}

void updateListeningAnimation() {
  if (state != LISTENING) return;

  unsigned long now = millis();
  if (now < nextListenFrame) return;

  listenFrame = !listenFrame;
  showFace(listenFrame ? listen2 : listen1);
  nextListenFrame = now + 350;
}

void updateBootAnimation() {
  if (state != BOOTING) return;

  unsigned long now = millis();
  if (now < nextBootFrame) return;
  nextBootFrame = now + 140;
  bootFrame = (bootFrame + 1) % 3;

  if (bootFrame == 0) showFace(boot1);
  else if (bootFrame == 1) showFace(boot2);
  else showFace(boot3);
}

void setup() {
  // Establish safe motor outputs before doing anything else.
  pinMode(LEFT_IN1, OUTPUT);
  pinMode(LEFT_IN2, OUTPUT);
  pinMode(RIGHT_IN3, OUTPUT);
  pinMode(RIGHT_IN4, OUTPUT);
  if (USE_PWM_ENABLE) {
    pinMode(LEFT_ENABLE, OUTPUT);
    pinMode(RIGHT_ENABLE, OUTPUT);
  }
  stopMotors();

  Serial.begin(115200);
  Serial.setTimeout(25);
  Wire.begin();

  matrix.shutdown(0, false);
  matrix.setIntensity(0, 3);
  matrix.clearDisplay(0);

  randomSeed(analogRead(A0));
  lastHostCommand = millis();
  setState(BOOTING);
}

void loop() {
  readCommands();
  for (byte i = 0; i < MAX_DYNAMIC_DEVICES; i++) {
    if (dynamicDevices[i].used && dynamicDevices[i].type == HW_HALL) {
      int value = digitalRead(dynamicDevices[i].pin1);
      if (value == HIGH && dynamicDevices[i].lastInput == LOW) dynamicDevices[i].pulses++;
      dynamicDevices[i].lastInput = value;
    }
  }
  updateMotorWatchdog();
  updateHostWatchdog();
  updateIdleAnimation();
  updateListeningAnimation();
  updateTalkingAnimation();
  updateBootAnimation();
  updateUpdatingAnimation();
  updateOfflineAnimation();
}
