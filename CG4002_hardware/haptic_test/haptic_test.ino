// Standalone test for the vibration motor module (IN/VCC/GND type).
// Not part of the main production sketch -- upload this alone to bench-test
// the motor and GPIO25 wiring in isolation before wiring it into the IMU pipeline.

const int VIB_PIN = 25;

void setup() {
  pinMode(VIB_PIN, OUTPUT);
  digitalWrite(VIB_PIN, LOW);

  Serial.begin(115200);
  delay(1000);
  Serial.println("Vibration motor standalone test starting...");
}

void loop() {
  // 1) Simple ON/OFF test
  Serial.println("ON (digitalWrite HIGH)");
  digitalWrite(VIB_PIN, HIGH);
  delay(1000);

  Serial.println("OFF (digitalWrite LOW)");
  digitalWrite(VIB_PIN, LOW);
  delay(1000);

  // 2) PWM ramp test: weak -> strong
  for (int duty = 50; duty <= 255; duty += 25) {
    analogWrite(VIB_PIN, duty);
    Serial.print("PWM duty=");
    Serial.println(duty);
    delay(300);
  }
  analogWrite(VIB_PIN, 0);
  Serial.println("PWM OFF");

  delay(2000);
}
