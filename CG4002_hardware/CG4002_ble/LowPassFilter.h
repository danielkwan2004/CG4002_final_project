#ifndef LOW_PASS_FILTER_H
#define LOW_PASS_FILTER_H


class LowPassFilter {

public:

  LowPassFilter();

  float update(float input, float alpha);

  void reset();


private:

  float value;
  bool initialized;
};


#endif