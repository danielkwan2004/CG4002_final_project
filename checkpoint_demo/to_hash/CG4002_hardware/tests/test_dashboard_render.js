// Source-level rendering unit tests. This is a minimal DOM stub, not a browser
// or a hardware simulation; real browser layout is verified separately.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const web = path.join(__dirname, "..", "diagnostics", "demo_web");
const element = () => ({textContent:"", hidden:false, dataset:{}, setAttribute(){}, replaceChildren(){}, append(){}, addEventListener(){}});
const ids = Object.fromEntries([...fs.readFileSync(path.join(web,"index.html"),"utf8").matchAll(/id="([^"]+)"/g)].map(m => [m[1], element()]));
const document = {getElementById(id){assert.ok(ids[id], `Unknown DOM id: ${id}`); return ids[id];},
  createElement:element, createElementNS:element, addEventListener(){}};
const context = vm.createContext({document, window:{}, console});
let source = fs.readFileSync(path.join(web,"app.js"),"utf8");
assert.match(source, /\npoll\(\);\s*$/);
source = source.replace(/\npoll\(\);\s*$/, ""); // test render(), not network polling
vm.runInContext(source, context);

function fixture() {
  return {mode:"replay",state:"complete",node:1,elapsed_s:50,packet_age_s:1,
    sample_age_s:null,latest:null,burst:0,invalid_packets:0,duplicates:0,points:[],events:[],
    metadata:{replay_source:"SYNTHETIC RENDER UNIT TEST"},summary:{boot:77,bursts:{},
      observed_startup:false,unseen_burst_count:0,
      timing:{produced:30001,achieved_hz:200,mean_interval_us:5000,min_interval_us:4805,
        max_interval_us:5156,skipped_deadlines:0,buffer_drops:0},
      latest_device_counters:{failed:174,bursts_started:14},
      finalized_burst_totals:{sender_attempted:4355,received_unique:1857,accepted_not_received:2324},
      capture_counter_changes:{failed:96,diag_failed:0,dropped:0,skipped_deadlines:0},
      capture_delivery:{sender_attempted:1953,sender_accepted:1857,received_unique:1857,
        local_send_failures:96,accepted_not_received:0,received_percent_of_attempted:95.0845,
        start_seq:20201,bursts_started:7,unseen_burst_count:0,finalized_burst_ids:["8"],
        historical_burst_ids:["1","2","3","4","5","6","7"],partial_burst_ids:[],pending_burst_ids:[]}}};
}
function render(data) { context.data = data; vm.runInContext("render(data)", context); }

let data = fixture(); render(data);
assert.equal(ids["burst-count"].textContent, "7");
assert.equal(ids.delivery.textContent, "1,953 → 1,857 → 1,857");
assert.match(ids["quality-warning"].textContent, /96 final local/);
assert.doesNotMatch(ids["quality-warning"].textContent, /2324|2,324|174/);
assert.match(ids.coverage.textContent, /Excluded historical bursts: 7/);
assert.equal(ids["queue-status"].hidden, true);

data = fixture();
Object.assign(data.summary.capture_delivery,{sender_attempted:100,sender_accepted:100,received_unique:100,
  local_send_failures:0,accepted_not_received:0,received_percent_of_attempted:100});
data.summary.capture_counter_changes.failed = 0;
data.summary.txqueue = {offered:100,accepted:100,pending:0,dropped:0,capacity:128,high_water:40,
  max_age_ms:240,batch_size:5,flush_ms:20,retry_ms:10,max_age_limit_ms:1000,overflow:0,expired:0,permanent:0,cancelled:0};
data.summary.capture_queue_changes = {dropped:0,recovered:25,retries:5};
data.summary.transport = {report:10,wifi_status:3,rssi_dbm:-40,disconnects:0,last_disconnect_reason:0,
  heap_free:180000,errors:[5,0,0,0],failed:5,last_stage:3,last_errno:12,last_data:true,last_ms:20000,
  last_wifi:3,last_rssi:-40,last_rssi_age_ms:100,last_heap:170000};
render(data);
assert.equal(ids["quality-warning"].hidden,true);
assert.equal(ids["queue-status"].hidden,false);
assert.match(ids["queue-status"].textContent,/25 samples recovered/);
assert.match(ids.transport.textContent,/ENOMEM 5/); // raw errors are not hidden
assert.match(ids["delivery-note"].textContent,/100.0% captured/);

data.summary.txqueue.pending=5; data.summary.txqueue.accepted=95;
data.summary.capture_delivery.finalized_burst_ids=[];
data.summary.capture_delivery.pending_burst_ids=["8"];
render(data);
assert.equal(ids.delivery.textContent,"—");
assert.match(ids["queue-status"].textContent,/5 samples pending/);
console.log("PASS: actual dashboard renderer uses capture-scoped totals; recovered errors remain visible but are not final losses; pending is not finalized delivery");
