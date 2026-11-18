"""Physical BLE-P1 cues only; your teammate's client owns Bluetooth and data logs."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time

PHASES = [
    ('reference',30,'Gently sway in natural ready stance. No steps or intentional wrist actions. Reference setup may be silent.',()),
    ('still',10,'Stand comfortably still; let pending output drain.',()),
    ('paddle_settle',8,'Forearm pod supported untouched; paddle held. Settle.',()),
    ('paddle_only',24,'Move ONLY the paddle at each cue; forearm pod stays supported.',
     ('One comfortable small paddle rotation out/back in about 1 s; return to rest.',)*3),
    ('forearm_settle',8,'Paddle supported untouched; forearm pod attached. Settle.',()),
    ('forearm_only',24,'Move ONLY your forearm at each cue; paddle stays supported.',
     ('One gentle forearm lift/rotation out/back in about 1 s; return to rest.',)*3),
    ('reattach_settle',10,'Forearm pod mounted, instrumented paddle held. Settle into ready stance.',()),
    ('compact',24,'SMALL WRIST actions only at numbered cues; forearm near ready.',
     ('One SMALL wrist rotation out/back in about 0.5 s. No arm swing; then rest.',)*3),
    ('normal',24,'One comfortable movement at each cue; return to ready and rest.',
     ('One underhand movement out/back in about 1 s.',
      'One backhand movement out/back in about 1 s.',
      'One overhand movement out/back in about 1 s.')),
    ('footwork',15,'Gentle left/right side steps; no intentional paddle action. Extra transmissions are acceptable.',()),
    ('compact_stepping',24,'Keep the SAME gentle side steps. At each cue use SMALL WRIST motion only.',
     ('KEEP STEPPING: one SMALL wrist rotation out/back in about 0.5 s; then continue the same steps.',)*3),
    ('final_still',12,'Stop steps and wrist motion. Hold still; wait for output to settle.',()),
]
PAUSES = {
    'paddle_settle':'Support the powered forearm pod on a stable surface. Hold the paddle without disturbing that pod.',
    'forearm_settle':'Support the paddle on a stable surface. Attach the forearm pod; leave the paddle untouched.',
    'reattach_settle':'Wear the forearm pod in its usual position and hold the instrumented paddle.',
}
CUE_OFFSETS = (4,11,18)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true',help='Print the procedure without running it')
    args=parser.parse_args(argv)
    if args.describe:
        print(json.dumps(dict(timed_seconds=sum(p[1] for p in PHASES),cues=sum(len(p[3]) for p in PHASES),
                              setup_pauses=len(PAUSES),phases=PHASES),indent=2))
        return
    print('BLE-P1 prompts only: this script DOES NOT connect to BLE or record sensor data.')
    print('Follow BLE_PLAY_TEST.md: both nodes already calibrated, forearm attached, normal BLE client running.')
    print('Ask your teammate to save actual BLE batches and combined SENSOR_DATA logs; source1 diagnostics off.')
    input('Gently sway in ready stance. Once BOTH nodes finish handshake/sync, press ENTER to start the 30 s reference wait: ')
    folder=Path(__file__).resolve().parent/'captures'/datetime.now().strftime('ble_p1_%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();events=[];completed=False;notes=''
    def record(kind,**fields):
        item=dict(kind=kind,elapsed_s=time.monotonic()-started,wall_time=datetime.now().astimezone().isoformat(),**fields)
        events.append(item)
        with (folder/'prompt_events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(item)+'\n')
        return item
    try:
        for phase,seconds,message,cues in PHASES:
            if phase in PAUSES:
                record('setup_pause',phase=phase,message=PAUSES[phase])
                input('\n'+PAUSES[phase]+' Press ENTER when ready (unlimited time): ')
            record('phase_start',phase=phase,seconds=seconds,message=message)
            print(f'\n[{time.monotonic()-started:6.1f}s] {phase}: {seconds} s. {message}',flush=True)
            phase_start=time.monotonic();next_cue=0
            while time.monotonic()-phase_start<seconds:
                if next_cue<len(cues) and time.monotonic()-phase_start>=CUE_OFFSETS[next_cue]:
                    record('cue',phase=phase,cue=next_cue+1,message=cues[next_cue])
                    print(f'[{time.monotonic()-started:6.1f}s] CUE {next_cue+1}: {cues[next_cue]}',flush=True)
                    next_cue+=1
                time.sleep(.02)
            record('phase_end',phase=phase)
        completed=True
        notes=input('\nDone. Any missed/wrong cues, absent data, stale values or connection problems? Enter notes (or none): ')
    except KeyboardInterrupt:
        notes='Interrupted by operator; retain partial evidence.'
        record('interrupted')
    finally:
        summary=dict(evidence_kind='operator_prompts_only_no_sensor_capture',protocol_completed=completed,
            physical_motion_success='REQUIRES_REVIEW_OF_TEAMMATE_BLE_LOGS',notes=notes,
            planned_timed_seconds=sum(p[1] for p in PHASES),expected_cues=sum(len(p[3]) for p in PHASES),
            actual_cues=sum(e['kind']=='cue' for e in events),BLE_client_modified=False)
        (folder/'operator_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print('Return this prompt folder AND the actual BLE/combined JSON logs:',folder)


if __name__=='__main__': main()
