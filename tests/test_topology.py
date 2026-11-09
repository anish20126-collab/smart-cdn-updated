"""Validate the shared port map against the actual Mininet topology (no network startup)."""
import unittest
from network_config import HOSTS, LINK_PORTS
try:
    from topology import SmartCDN
except ModuleNotFoundError:
    SmartCDN = None

@unittest.skipIf(SmartCDN is None, "Mininet uses system Python; run python3 -m unittest discover -s tests -p test_topology.py")
class TopologyTests(unittest.TestCase):
    def test_topology_addresses_ports_and_links(self):
        topology=SmartCDN()
        self.assertEqual(len(topology.switches()),6)
        self.assertEqual(len(topology.hosts()),10)
        self.assertEqual(len(topology.links()),19)
        for address,host in HOSTS.items():
            info=topology.nodeInfo(host['name'])
            self.assertEqual(info['ip'],address+'/24')
            self.assertEqual(info['mac'],host['mac'])
            self.assertEqual(topology.port('s'+str(host['switch']),host['name'])[0],host['port'])
        for (source,destination),(port,capacity) in LINK_PORTS.items():
            self.assertEqual(topology.port('s'+str(source),'s'+str(destination))[0],port)
            self.assertEqual(topology.linkInfo('s'+str(source),'s'+str(destination))['bw'],capacity)
