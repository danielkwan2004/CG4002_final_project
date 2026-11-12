#include "LowPassFilter.h"


LowPassFilter::LowPassFilter() {

  value = 0.0;
  initialized = false;
}


float LowPassFilter::update(float input, float alpha) {

  if (!initialized) {

    value = input;
    initialized = true;

    return value;
  }


  value =
      alpha * input
      + (1.0 - alpha) * value;


  return value;
}


void LowPassFilter::reset() {

  value = 0.0;
  initialized = false;
}