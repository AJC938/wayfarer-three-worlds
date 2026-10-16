#include <Arduino.h>
#include <stdio.h>
#include <string.h>

// Arduino UNO controller for Wayfarer.
// Arduino -> Python: x,y,sw\n at 9600 baud.
// Python -> Arduino: S,alive,level,coins,hp,boss,event\n
const byte PIN_X = A0;       // Verified physical up/down axis
const byte PIN_Y = A1;       // Verified physical left/right axis
const byte PIN_SW = 2;
const byte LED_GREEN = 8;    // Player alive
const byte LED_RED = 9;      // Damage / low-health danger
const byte LED_BLUE = 10;    // Coin collection / interactions
const byte LED_YELLOW = 13;  // Level transitions / boss events
const unsigned long INPUT_INTERVAL_MS = 20;

char lineBuffer[96];
byte lineLength = 0;
bool discardingLine = false;
unsigned long nextInputAt = 0;
unsigned long eventUntil = 0;
bool alive = true;
int level = 1;
int coins = 0;
int hp = 3;
int bossState = 0;
char eventName[16] = "-";

bool knownEvent(const char *event) {
  return strcmp(event, "-") == 0 || strcmp(event, "LEVEL") == 0 ||
         strcmp(event, "COIN") == 0 || strcmp(event, "DAMAGE") == 0 ||
         strcmp(event, "DEATH") == 0 || strcmp(event, "ENEMY") == 0 ||
         strcmp(event, "BOSS") == 0 || strcmp(event, "BOSS_HIT") == 0 ||
         strcmp(event, "BOSS_DOWN") == 0 || strcmp(event, "WIN") == 0;
}

void setEvent(const char *event) {
  strncpy(eventName, event, sizeof(eventName) - 1);
  eventName[sizeof(eventName) - 1] = '\0';
  eventUntil = millis() + 900;
}

void handleHostLine(char *line) {
  int newAlive, newLevel, newCoins, newHp, newBoss;
  int consumed = -1;
  char event[16] = "";
  int fields = sscanf(line, "S,%d,%d,%d,%d,%d,%15[^,\r\n]%n",
                      &newAlive, &newLevel, &newCoins, &newHp, &newBoss,
                      event, &consumed);

  // Require all six fields, a known event token, and no trailing garbage.
  if (fields != 6 || consumed < 0 || line[consumed] != '\0' || !knownEvent(event)) return;
  if ((newAlive != 0 && newAlive != 1) || newLevel < 1 || newLevel > 3 ||
      newCoins < 0 || newHp < 0 || newHp > 3 || newBoss < 0 || newBoss > 2) return;

  alive = (newAlive == 1);
  level = newLevel;
  coins = newCoins;
  hp = newHp;
  bossState = newBoss;
  if (strcmp(event, "-") != 0) setEvent(event);
}

void readHost() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!discardingLine) {
        lineBuffer[lineLength] = '\0';
        handleHostLine(lineBuffer);
      }
      lineLength = 0;
      discardingLine = false;
    } else if (discardingLine) {
      // Ignore the rest of an overlong record up to its newline.
    } else if (c != '\r') {
      if (lineLength < sizeof(lineBuffer) - 1) {
        lineBuffer[lineLength++] = c;
      } else {
        lineLength = 0;
        discardingLine = true;
      }
    }
  }
}

void sendJoystick() {
  // Largest record is 13 bytes including CRLF; skip a sample if TX is busy.
  if (Serial.availableForWrite() < 13) return;
  Serial.print(analogRead(PIN_X));
  Serial.print(',');
  Serial.print(analogRead(PIN_Y));
  Serial.print(',');
  Serial.println(digitalRead(PIN_SW) == LOW ? 1 : 0);
}

void updateLeds() {
  unsigned long now = millis();
  bool victory = strcmp(eventName, "WIN") == 0;
  bool activeEvent = now < eventUntil;
  bool lowHealth = alive && hp == 1;
  bool damageEvent = strcmp(eventName, "DAMAGE") == 0 || strcmp(eventName, "DEATH") == 0;
  bool collectionEvent = strcmp(eventName, "COIN") == 0 ||
                         strcmp(eventName, "ENEMY") == 0 ||
                         strcmp(eventName, "BOSS_HIT") == 0;
  bool progressEvent = strcmp(eventName, "LEVEL") == 0 ||
                       strcmp(eventName, "BOSS") == 0 ||
                       strcmp(eventName, "BOSS_DOWN") == 0;

  digitalWrite(LED_GREEN, alive && hp > 0 ? HIGH : LOW);
  digitalWrite(LED_RED, (lowHealth && (now / 350) % 2 == 0) ||
                        (damageEvent && activeEvent && (now / 120) % 2 == 0) ? HIGH : LOW);
  digitalWrite(LED_BLUE, collectionEvent && activeEvent && (now / 100) % 2 == 0 ? HIGH : LOW);
  digitalWrite(LED_YELLOW, progressEvent && activeEvent && (now / 180) % 2 == 0 ? HIGH : LOW);

  if (victory) {
    bool blink = (now / 90) % 2 == 0;
    digitalWrite(LED_GREEN, blink ? HIGH : LOW);
    digitalWrite(LED_RED, blink ? HIGH : LOW);
    digitalWrite(LED_BLUE, blink ? HIGH : LOW);
    digitalWrite(LED_YELLOW, blink ? HIGH : LOW);
  }
}

void setup() {
  pinMode(PIN_SW, INPUT_PULLUP);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  Serial.begin(9600);
  nextInputAt = millis();
}

void loop() {
  readHost();
  updateLeds();
  unsigned long now = millis();
  if ((long)(now - nextInputAt) >= 0) {
    nextInputAt = now + INPUT_INTERVAL_MS;
    sendJoystick();
  }
}
