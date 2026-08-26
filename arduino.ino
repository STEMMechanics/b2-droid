#include <LedControl.h>

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

  matrix.shutdown(0, false);
  matrix.setIntensity(0, 3);
  matrix.clearDisplay(0);

  randomSeed(analogRead(A0));
  lastHostCommand = millis();
  setState(BOOTING);
}

void loop() {
  readCommands();
  updateMotorWatchdog();
  updateHostWatchdog();
  updateIdleAnimation();
  updateListeningAnimation();
  updateTalkingAnimation();
  updateBootAnimation();
  updateUpdatingAnimation();
  updateOfflineAnimation();
}
