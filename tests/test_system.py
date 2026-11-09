import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from client import fetch
from server import ContentServer
from protocol import read_header,send_header
from routing import shortest_path,select_server
from network_config import HOSTS,LINK_PORTS,SERVERS

class PolicyTests(unittest.TestCase):
    def test_path_and_failure(self):
        cost,path=shortest_path(5,3,set(),{})
        self.assertEqual(path,[5,3])
        _,reroute=shortest_path(5,3,{(5,3),(3,5)},{})
        self.assertNotEqual(reroute,path)
        self.assertEqual((reroute[0],reroute[-1]),(5,3))
        self.assertEqual(shortest_path(5,3,set(LINK_PORTS),{})[1],[])

    def test_measured_load_health_congestion(self):
        health={s:dict(healthy=True,active=0,mbps=0) for s in SERVERS}
        first=select_server('10.0.0.21',health,set(),{})
        health[first[1]]['active']=20
        self.assertNotEqual(select_server('10.0.0.21',health,set(),{})[1],first[1])
        health={s:dict(healthy=False) for s in SERVERS}
        self.assertIsNone(select_server('10.0.0.21',health,set(),{}))
        _,path=shortest_path(5,3,set(),{(5,LINK_PORTS[5,3][0]):19.9})
        self.assertNotEqual(path,[5,3])

class TransferTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.data=bytes(range(256))*4096
        (self.root/'video.mp4').write_bytes(self.data)
        try:
            self.server=ContentServer(('127.0.0.1',0),'srv-test',self.root)
        except PermissionError:
            self.directory.cleanup()
            self.skipTest('Sandbox denies socket creation; run these tests in the VM terminal')
        self.port=self.server.server_address[1]
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True); self.worker.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(); self.directory.cleanup()

    def test_actual_binary_transfer_and_health(self):
        output=self.root/'download.bin'
        result=fetch('127.0.0.1','video.mp4',output,port=self.port)
        self.assertTrue(result['ok'],result)
        self.assertEqual(output.read_bytes(),self.data)
        self.assertGreater(result['throughput_mbps'],0)
        with socket.create_connection(('127.0.0.1',self.port)) as sock:
            send_header(sock,{'op':'health'})
            with sock.makefile('rb') as stream: health=read_header(stream)
        self.assertEqual(health['requests'],1)
        self.assertEqual(health['bytes'],len(self.data))

    def test_missing_and_traversal(self):
        for name in ['absent','../video.mp4']:
            self.assertFalse(fetch('127.0.0.1',name,port=self.port)['ok'])

    def test_concurrent_six_clients(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:fetch('127.0.0.1','video.mp4',port=self.port),range(6)))
        self.assertTrue(all(r['ok'] for r in results))

    def test_integrity_failure_removes_partial_file(self):
        size,digest=self.server.catalog['video.mp4']
        self.server.catalog['video.mp4']=(size,'0'*64)
        output=self.root/'bad.bin'
        result=fetch('127.0.0.1','video.mp4',output,port=self.port)
        self.assertFalse(result['ok']); self.assertIn('SHA-256',result['error'])
        self.assertFalse(output.exists()); self.assertFalse(output.with_suffix('.bin.part').exists())

if __name__=='__main__': unittest.main()
