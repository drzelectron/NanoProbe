#include <Arduino.h>

enum WaveType { SINE = 0, RECTANGULAR = 1, TRIANGULAR = 2, SAWTOOTH = 3 };

uint8_t waveType = SINE;
float frequency = 50.0;
uint16_t quantization = 100;
uint8_t dutyCycle = 50;

#define MAX_POINTS 250
uint8_t waveCycle[MAX_POINTS];
unsigned long delayUs = 2000;

void generateWaveCycle() {
  if (quantization > MAX_POINTS) quantization = MAX_POINTS;
  if (quantization < 10) quantization = 10;
  
  for (uint16_t i = 0; i < quantization; i++) {
    float phase = (float)i / quantization;
    uint8_t val = 0;

    if (waveType == SINE) {
      float rad = phase * 2.0 * 3.14159265;
      val = (uint8_t)((sin(rad) + 1.0) * 127.5);
    } 
    else if (waveType == RECTANGULAR) {
      float threshold = (float)dutyCycle / 100.0;
      val = (phase < threshold) ? 255 : 0;
    } 
    else if (waveType == TRIANGULAR) {
      if (phase < 0.5) {
        val = (uint8_t)(phase * 2.0 * 255.0);
      } else {
        val = (uint8_t)((1.0 - phase) * 2.0 * 255.0);
      }
    } 
    else if (waveType == SAWTOOTH) {
      val = (uint8_t)(phase * 255.0);
    }
    waveCycle[i] = val;
  }

  if (frequency > 0 && quantization > 0) {
    delayUs = (unsigned long)(1000000.0 / (frequency * quantization));
    if (delayUs < 100) delayUs = 100;
  }
}

void setup() {
  Serial.begin(115200);
  DDRD |= 0x7C; // Set D2-D6 as outputs on PORTD (pins 2 to 6)
  pinMode(A0, INPUT);
  generateWaveCycle();
}

void loop() {
  if (Serial.available() > 0) {
    String inputStr = Serial.readStringUntil('\n');
    inputStr.trim();
    if (inputStr.startsWith("CFG,")) {
      int firstComma = inputStr.indexOf(',', 4);
      int secondComma = inputStr.indexOf(',', firstComma + 1);
      int thirdComma = inputStr.indexOf(',', secondComma + 1);

      if (firstComma != -1 && secondComma != -1 && thirdComma != -1) {
        waveType = inputStr.substring(4, firstComma).toInt();
        frequency = inputStr.substring(firstComma + 1, secondComma).toFloat();
        quantization = (uint16_t)inputStr.substring(secondComma + 1, thirdComma).toInt();
        dutyCycle = inputStr.substring(thirdComma + 1).toInt();
        generateWaveCycle();
      }
    }
  }

  for (uint16_t i = 0; i < quantization; i++) {
    uint8_t val = waveCycle[i];
    PORTD = (PORTD & 0x83) | ((val >> 3) << 2);

    uint16_t adcVal = analogRead(A0);

    Serial.print(val);
    Serial.print(',');
    Serial.println(adcVal);

    if (delayUs > 0) {
      delayMicroseconds(delayUs);
    }
  }
}
