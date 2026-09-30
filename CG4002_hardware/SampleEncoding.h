#ifndef SAMPLE_ENCODING_H
#define SAMPLE_ENCODING_H

#include "TxQueue.h"
#include <stdio.h>

inline int encodeSample(const QueuedSample& item, char* packet, size_t capacity) {
  const SensorFrame& f = item.frame;
  return snprintf(packet, capacity,
      "4,%u,%lu,%lu,%lu,%lu,%lu,%lu,%d,%d,%d,%d,%d,%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%u\n",
      f.node_id, (unsigned long)item.boot, (unsigned long)item.burst,
      (unsigned long)item.index, (unsigned long)f.seq,
      f.timestamp_us, f.interval_us, f.ax, f.ay, f.az, f.gx, f.gy, f.gz,
      f.ax_g, f.ay_g, f.az_g, f.gx_dps, f.gy_dps, f.gz_dps,
      f.ax_filtered_g, f.ay_filtered_g, f.az_filtered_g,
      f.gx_filtered_dps, f.gy_filtered_dps, f.gz_filtered_dps, f.status_flags);
}

#endif
