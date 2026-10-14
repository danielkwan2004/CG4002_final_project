"use strict";
const $ = id => document.getElementById(id);
const number = (value, digits = 0) => Number.isFinite(value) ? value.toLocaleString(undefined, {minimumFractionDigits: digits, maximumFractionDigits: digits}) : "—";
const stamp = value => `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(Math.floor(value % 60)).padStart(2, "0")}`;
const text = (id, value) => { if ($(id).textContent !== value) $(id).textContent = value; };
const labels = {
  waiting: ["WAITING FOR DEVICE", "Ready when you are.", "Power on or reset the battery-powered node. Keep it flat and still through calibration."],
  calibrating: ["DEVICE CONNECTED", "Calibrating…", "Keep the sensor flat, +Z upward, and still. Let the device finish before moving it."],
  moving: ["DEVICE CONNECTED · GATE ACTIVE", "Motion detected.", "The device movement gate is active. Movement samples are arriving at the laptop."],
  settled: ["DEVICE CONNECTED · GATE IDLE", "Settled.", "No active movement burst. The device keeps sampling and sending diagnostics while full movement packets are gated off."],
  disconnected: ["CONNECTION WARNING", "Signal interrupted.", "No recent packets from this node. Check power, hotspot, destination IP and firewall. Silence does not mean motion stopped."],
  fault: ["DEVICE FAULT", "Check the hardware.", "The node reported a fault. Inspect power, IMU wiring and the detailed capture log before continuing."],
  unknown: ["DEVICE CONNECTED", "Awaiting motion status.", "Packets are arriving, but there is no recent movement-state evidence. Waiting for the next device diagnostic."],
  complete: ["SESSION COMPLETE", "Session complete.", "The values below are retained from the completed session. They are not live readings."]
};
function svgElement(tag, attrs, content) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (content !== undefined) element.textContent = content;
  return element;
}
function chart(data, threshold) {
  const end = Math.max(20, data.elapsed_s), start = end - 20;
  const points = data.points.filter(p => p.t >= start && p.t <= end);
  const top = Math.max(100, Math.ceil(Math.max(threshold ?? 0, ...points.map(p => p.value)) / 100) * 100);
  const x = t => 48 + (t - start) / 20 * 674;
  const y = value => 176 - value / top * 151;
  const grid = [], ticks = [];
  for (let i = 0; i <= 2; i++) {
    const value = top * i / 2;
    grid.push(svgElement("line", {x1:48, x2:722, y1:y(value), y2:y(value)}));
    ticks.push(svgElement("text", {x:39, y:y(value)+4, "text-anchor":"end"}, number(value)));
  }
  for (let i = 0; i <= 4; i++) {
    const t = start + i * 5;
    ticks.push(svgElement("text", {x:x(t), y:196, "text-anchor":i===0 ? "start" : i===4 ? "end" : "middle"}, `${number(t, 0)} s`));
  }
  ticks.push(svgElement("text", {x:48,y:13}, "°/s"));
  ticks.push(svgElement("text", {x:722,y:216,"text-anchor":"end"}, "Receiver elapsed time"));
  $("chart-grid").replaceChildren(...grid);
  $("chart-labels").replaceChildren(...ticks);
  const marks = Number.isFinite(threshold) ? [
    svgElement("line", {x1:48,x2:722,y1:y(threshold),y2:y(threshold)}),
    svgElement("text", {x:718,y:y(threshold)-5,"text-anchor":"end"}, `Start ${number(threshold)} °/s`)
  ] : [];
  $("chart-threshold").replaceChildren(...marks);
  let previous = null;
  const path = points.map(p => {
    const connected = previous && previous.burst === p.burst && p.t - previous.t < 0.15;
    previous = p;
    return `${connected ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.value).toFixed(1)}`;
  }).join(" ");
  $("chart-line").setAttribute("d", path);
}
let eventSignature = "";
function render(data) {
  const state = data.state, replay = data.mode === "replay";
  const [connection, title, note] = labels[state] || labels.unknown;
  $("hero").dataset.state = state;
  text("connection", replay ? `REPLAY · ${connection.replace("DEVICE CONNECTED", "RECORDED DEVICE")}` : connection);
  text("status", title);
  text("status-note", replay && state === "complete" ? "Recorded replay has finished. No live UDP connection was used and no source files were changed." : note);
  text("mode", replay ? "RECORDED REPLAY" : "LIVE DEMO");
  $("replay").hidden = !replay;
  text("node", `Node ${data.node}`);
  text("identity", data.summary ? `Node ${data.node} · boot ${data.summary.boot.toString(16).padStart(8, "0")}` : `Waiting for node ${data.node}`);
  text("heartbeat", data.packet_age_s === null ? "No packets yet" : `Last packet ${number(data.packet_age_s, 1)} s ago${state === "complete" ? " at session end" : ""}`);
  const powers = {"lipo-usb-disconnected":"LiPo / USB disconnected · operator-reported", usb:"USB power · operator-reported", unknown:"Power source not specified"};
  text("power", replay ? `Saved capture · ${number(data.metadata.replay_speed || 1, 1)}× replay` : (powers[data.metadata.operator_reported_power_source] || powers.unknown));
  const s = data.summary, timing = s?.timing, c = s?.configuration, totals = s?.capture_delivery;
  const changes = s?.capture_counter_changes, q = s?.txqueue, qc = s?.capture_queue_changes;
  text("burst-count", number(totals?.bursts_started));
  text("burst-note", state === "moving" ? `Burst ${data.burst} active` : state === "settled" ? "Device gate idle" : "Reported in device diagnostics");
  text("rate", number(timing?.achieved_hz, 2));
  text("interval", timing?.mean_interval_us != null ? `Mean ${number(timing.mean_interval_us/1000,3)} ms · range ${number(timing.min_interval_us/1000,3)}–${number(timing.max_interval_us/1000,3)} ms` : "Completed register reads · waiting");
  text("acquired", number(timing?.produced));
  const finalized = totals?.finalized_burst_ids.length || 0;
  const incomplete = (totals?.pending_burst_ids.length || 0) + (totals?.unseen_burst_count || 0);
  const warnings = [];
  if (data.invalid_packets) warnings.push(`${data.invalid_packets} unrecognized packet(s); update receiver and firmware together`);
  if (c && !s.range_readback_verified) warnings.push("sensor configuration is not verified");
  if (changes?.skipped_deadlines) warnings.push(`${changes.skipped_deadlines} skipped acquisition slot(s) since capture baseline`);
  if (changes?.dropped) warnings.push(`${changes.dropped} acquisition buffer drop(s) since capture baseline`);
  const finalDrops = Math.max(totals?.local_send_failures || 0, changes?.failed || 0, qc?.dropped || 0);
  if (finalDrops) warnings.push(`${finalDrops} final local sample drop(s) in capture evidence`);
  if (changes?.diag_failed) warnings.push(`${changes.diag_failed} diagnostic send error(s) since capture baseline; summaries are repeated`);
  if (totals?.accepted_not_received) warnings.push(`${totals.accepted_not_received} accepted sample(s) not yet captured in closed bursts`);
  if (totals?.pending_burst_ids.some(id => s.bursts[id]?.complete_sender_summary && !s.bursts[id]?.counts_consistent)) warnings.push("inconsistent burst evidence; do not infer packet loss");
  if (totals?.unseen_burst_count) warnings.push(`${totals.unseen_burst_count} new burst(s) lack evidence`);
  text("quality-warning", warnings.length ? `Check evidence: ${warnings.join(" · ")}.` : "");
  $("quality-warning").hidden = warnings.length === 0;
  text("delivery", finalized ? `${number(totals.sender_attempted)} → ${number(totals.sender_accepted)} → ${number(totals.received_unique)}` : "—");
  text("delivery-note", finalized ? `This capture · ${number(totals.local_send_failures)} final local drops + ${number(totals.accepted_not_received)} accepted but unreceived · ${number(totals.received_percent_of_attempted,1)}% captured${incomplete ? ` · ${incomplete} burst(s) pending / inconsistent` : ""}` : "This capture · waiting for final, consistent sender counts");
  text("queue-status", q ? `Buffered transmission · ${number(q.pending)} samples pending on device · ${number(qc?.recovered)} samples recovered after send errors · ${number(qc?.retries)} retry calls since capture baseline. Temporary errors are not final sample losses.` : "");
  $("queue-status").hidden = !q;
  const fresh = state === "moving" && data.sample_age_s !== null && data.sample_age_s < 0.75;
  text("sample-tag", !data.latest ? "NO SAMPLE YET" : fresh ? (replay ? "REPLAY SAMPLE" : "RECEIVING") : "LAST RECEIVED · HELD");
  text("sample-note", !data.latest ? "Movement samples appear here when the device gate opens." : fresh ? "Filtered sensor values from received movement packets." : `Last movement sample ${number(data.sample_age_s,1)} s ago${state === "complete" ? " at session end" : ""}. Held values, not current idle readings.`);
  if (state === "moving" && !fresh) text("status-note", "The last device report says the gate is active, but no fresh movement sample is available. Values below are held.");
  text("rotation", number(data.latest?.gyro_norm,1));
  text("acceleration", number(data.latest?.accel_deviation,3));
  $("saturation").hidden = !data.latest?.saturated;
  const axes = a => a.map(v => `${v >= 0 ? "+" : ""}${number(v,2)}`).join(" / ");
  text("gyro-axes", `Gyro X / Y / Z: ${data.latest ? axes(data.latest.gyro) + " °/s" : "—"}`);
  text("accel-axes", `Accel X / Y / Z: ${data.latest ? axes(data.latest.accel) + " g" : "—"}`);
  const signature = JSON.stringify(data.events);
  if (signature !== eventSignature) {
    $("events").replaceChildren(...data.events.map(event => {
      const row=document.createElement("li"), time=document.createElement("time"), message=document.createElement("span");
      time.textContent=stamp(event.seconds); message.textContent=event.text;
      row.append(time,message); return row;
    }));
    eventSignature=signature;
  }
  text("config", c ? `Configuration readback: ${s.range_readback_verified ? "verified" : "NOT VERIFIED"} · gyro ±${c.gyro_fs_dps} °/s (${c.gyro_lsb_per_dps} counts/°/s) · accel ±${c.accel_fs_g} g (${c.accel_lsb_per_g} counts/g).` : "Configuration readback: waiting.");
  text("thresholds", c ? `Gate starts at gyro ≥ ${c.gyro_start_dps} °/s OR acceleration deviation ≥ ${c.accel_start_g} g. Stops after BOTH are below ${c.gyro_stop_dps} °/s and ${c.accel_stop_g} g for ${c.quiet_ms} ms. Deviation is |filtered acceleration magnitude − 1 g|.` : "Thresholds: waiting for device configuration.");
  text("health", timing ? `Device boot: skipped slots ${timing.skipped_deadlines} · acquisition buffer drops ${timing.buffer_drops}. Current capture: duplicate samples ${data.duplicates} · finalized local drops ${totals.local_send_failures}. Acquisition statistics include idle; delivery excludes historical/partial/unfinished/inconsistent bursts and may change with late packets. Not an end-to-end latency measurement.` : "Timing / transport diagnostics: waiting.");
  const t = s?.transport;
  const stages = ["none", "format", "not-ready", "sendto", "short-send"];
  text("transport", t ? `Send diagnostics report ${t.report}: Wi-Fi status ${t.wifi_status} (3 = connected), RSSI ${t.rssi_dbm ? t.rssi_dbm + " dBm" : "unavailable"}, disconnect events ${t.disconnects} (last reason ${t.last_disconnect_reason}); free heap ${number(t.heap_free)} bytes. Failures by cause: ENOMEM ${t.errors[0]}, busy/no buffers ${t.errors[1]}, network ${t.errors[2]}, other ${t.errors[3]}. ${t.failed ? `Last failure: ${stages[t.last_stage]}, errno ${t.last_errno}, ${t.last_data ? "movement data" : "diagnostic"}, device uptime ${number(t.last_ms/1000,1)} s; Wi-Fi status then ${t.last_wifi}, cached RSSI ${t.last_rssi} dBm (age ${t.last_rssi_age_ms} ms), heap ${number(t.last_heap)} bytes.` : "No send failures in this report."} ENOMEM can indicate driver transmit-buffer pressure, not only low application heap. Snapshot precedes its own send.` : "Detailed send-error diagnostics unavailable so far. Older captures/firmware do not contain them; flash the diagnostic firmware for the next live test.");
  text("queue-details", q ? `Boot-wide transmit queue: ${q.offered} offered = ${q.accepted} accepted + ${q.pending} pending + ${q.dropped} final drops. Queue high-water ${q.high_water}/${q.capacity}; maximum observed queued age ${q.max_age_ms} ms. Batches up to ${q.batch_size}, flush ${q.flush_ms} ms, retry spacing ${q.retry_ms} ms, age limit ${q.max_age_limit_ms} ms. Final drops: overflow ${q.overflow}, expiry ${q.expired}, permanent ${q.permanent}, history eviction ${q.cancelled}. Retry/socket counters count datagrams; delivery counts unique samples. UDP acceptance is not acknowledgement by the laptop.` : "Transmit queue unavailable: this capture uses the older immediate-send firmware.");
  text("coverage", s ? `Startup observed: ${s.observed_startup ? "yes" : "no — joined an existing boot"}. Capture acquisition boundary: ${totals.start_seq ?? "unknown"}. Excluded historical bursts: ${totals.historical_burst_ids.length}; partial bursts: ${totals.partial_burst_ids.length}. New unseen bursts: ${totals.unseen_burst_count ?? "unknown until a baseline is available"}. Pending / inconsistent bursts: ${incomplete}. Error/recovery changes are measured from startup or the first received report; technical boot-wide counters and all raw evidence are retained.` : "Capture coverage: waiting.");
  text("evidence", replay ? `Read-only replay source: ${data.metadata.replay_source || "loading"}` : `Evidence folder: ${data.directory || "waiting for receiver startup"}`);
  chart(data, c?.gyro_start_dps ?? null);
}
async function poll() {
  try {
    const response = await fetch("/api/state", {cache:"no-store", signal:AbortSignal.timeout(2000)});
    if (!response.ok) throw new Error("Receiver unavailable");
    render(await response.json());
    $("server-warning").hidden = true;
  } catch (_) {
    $("server-warning").hidden = false;
    $("hero").dataset.state = "disconnected";
    text("connection", "RECEIVER UNAVAILABLE"); text("status", "Display disconnected.");
    text("status-note", "The browser cannot reach Python. Previously displayed readings are frozen, not live.");
    text("sample-tag", "FROZEN · RECEIVER OFFLINE");
  } finally { window.setTimeout(poll, 100); }
}
$("fullscreen").addEventListener("click", async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
  catch (_) { text("fullscreen", "Use browser F11"); }
});
document.addEventListener("fullscreenchange", () => text("fullscreen", document.fullscreenElement ? "Exit full screen" : "Full screen"));
poll();
