import json
import struct
import sys
import unittest
import asyncio
import tempfile
import types
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ble_receiver import HEADER,SAMPLE,decode_packet,Capture,run

def packet(seqs=(10,11),burst=1,session=2,events=None):
    events=events or [0]*len(seqs)
    return HEADER.pack(b'CG',1,1,len(seqs),0,77,session,burst)+b''.join(
        SAMPLE.pack(seq,seq*5000,5000,1.25,0,1,-123.5,0,0,14,event)
        for seq,event in zip(seqs,events))

class ReceiverTests(unittest.TestCase):
    def test_round_trip_units_boundaries(self):
        rows=decode_packet(packet(events=[1,2]))
        self.assertEqual(rows[0]['ax_g'],1.25)
        self.assertEqual(rows[0]['gx_dps'],-123.5)
        c=Capture()
        for r in rows:c.ingest(r)
        b=next(iter(c.bursts.values()))
        self.assertTrue(b['start_observed'] and b['end_observed'])

class LiveLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_ble_session_saves_real_files(self):
        class Scanner:
            @staticmethod
            async def find_device_by_filter(*args,**kwargs):return object()
        class Client:
            def __init__(self,*args,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def start_notify(self,uuid,callback):callback(None,packet(events=[1,2]))
            async def read_gatt_char(self,uuid):
                return json.dumps(dict(state='STREAMING',mtu=185,subscribed=True)).encode()
        with tempfile.TemporaryDirectory() as temp:
            args=types.SimpleNamespace(output=Path(temp),name='CG4002-Forearm',address=None,
                duration=.05,power_source='usb')
            with patch.dict(sys.modules,{'bleak':types.SimpleNamespace(BleakClient=Client,BleakScanner=Scanner)}):
                await run(args)
            folder=next(Path(temp).iterdir())
            summary=json.loads((folder/'summary.json').read_text())
            self.assertEqual(summary['received_samples'],2)
            self.assertEqual(summary['invalid_notifications'],0)
            self.assertEqual(len((folder/'samples.csv').read_text().splitlines()),3)
            self.assertTrue((folder/'status.jsonl').read_text())

    async def test_fake_disconnect_reconnect_keeps_sessions_separate(self):
        class Scanner:
            @staticmethod
            async def find_device_by_filter(*args,**kwargs):return object()
        class Client:
            connections=0
            def __init__(self,*args,**kwargs):
                Client.connections+=1; self.id=Client.connections
                self.callback=kwargs['disconnected_callback']
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def start_notify(self,uuid,callback):
                callback(None,packet((self.id*100,),session=self.id))
            async def read_gatt_char(self,uuid):
                if self.id==1:self.callback(self)
                return json.dumps(dict(state='STREAMING',mtu=185,subscribed=True)).encode()
        with tempfile.TemporaryDirectory() as temp:
            args=types.SimpleNamespace(output=Path(temp),name='CG4002-Forearm',address=None,
                duration=.05,power_source='usb')
            with patch.dict(sys.modules,{'bleak':types.SimpleNamespace(BleakClient=Client,BleakScanner=Scanner)}):
                await run(args)
            folder=next(Path(temp).iterdir())
            summary=json.loads((folder/'summary.json').read_text())
            self.assertEqual(len(summary['bursts']),2)
            self.assertTrue(all(b['sequence_gaps']==0 for b in summary['bursts'].values()))

class CaptureAccountingTests(unittest.TestCase):
    def test_queue_loss_is_counted_not_rejected(self):
        c=Capture()
        for r in decode_packet(packet((10,13))):c.ingest(r)
        self.assertEqual(next(iter(c.bursts.values()))['sequence_gaps'],2)
        for r in decode_packet(packet((11,12))):c.ingest(r)
        b=next(iter(c.bursts.values()))
        self.assertEqual(b['sequence_gaps'],0)
        self.assertEqual(b['received'],4)

    def test_idle_and_reconnect_gaps_are_not_loss(self):
        c=Capture()
        for p in (packet((10,)),packet((1000,),burst=2),packet((2000,),burst=2,session=3)):
            c.ingest(decode_packet(p)[0])
        self.assertEqual(len(c.bursts),3)
        self.assertTrue(all(b['sequence_gaps']==0 for b in c.bursts.values()))
        self.assertTrue(all(not b['start_observed'] for b in c.bursts.values()))

    def test_duplicates_do_not_increase_received(self):
        c=Capture();r=decode_packet(packet((10,)))[0]
        c.ingest(r);c.ingest(r)
        self.assertEqual(c.received,1)
        self.assertEqual(next(iter(c.bursts.values()))['duplicates'],1)

    def test_malformed_packets(self):
        good=packet()
        bad_float=bytearray(good); struct.pack_into('<f',bad_float,HEADER.size+12,float('nan'))
        for bad in (b'',good[:-1],good+b'x',b'XX'+good[2:],packet(events=[2,0]),bad_float,packet((11,10))):
            with self.subTest(bad=bad),self.assertRaises(ValueError):decode_packet(bad)

    def test_cpp_fixture_when_supplied(self):
        import os
        path=os.environ.get('BLE_PACKET_FIXTURE')
        if not path:self.skipTest('C++ fixture supplied by run_tests.cmd')
        rows=decode_packet(Path(path).read_bytes())
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]['ax_g'],1.25)
        self.assertEqual(rows[0]['gx_dps'],-123.5)

if __name__=='__main__':unittest.main()
