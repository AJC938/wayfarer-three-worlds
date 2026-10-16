// Hardware-only diagnostic for the tested UNO joystick and four LEDs.
// Tested direction map: A0 low=down, A0 high=up; A1 low=left, A1 high=right.
const byte PIN_X = A0;
const byte PIN_Y = A1;
const byte PIN_SW = 2;
const byte LED_GREEN = 8;   // Down
const byte LED_RED = 9;     // Up
const byte LED_BLUE = 10;   // Left
const byte LED_YELLOW = 13; // Right

void setup() {
  Serial.begin(9600);
  pinMode(PIN_SW, INPUT_PULLUP);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
}

void loop() {
  int x = analogRead(PIN_X);
  int y = analogRead(PIN_Y);
  int pressed = digitalRead(PIN_SW) == LOW ? 1 : 0;

  // This reproduces the already-verified physical direction-to-LED test.
  digitalWrite(LED_GREEN, x < 350 ? HIGH : LOW);   // Down
  digitalWrite(LED_RED, x > 700 ? HIGH : LOW);      // Up
  digitalWrite(LED_BLUE, y < 350 ? HIGH : LOW);     // Left
  digitalWrite(LED_YELLOW, y > 700 ? HIGH : LOW);   // Right

  Serial.print(x);
  Serial.print(',');
  Serial.print(y);
  Serial.print(',');
  Serial.println(pressed);
}
