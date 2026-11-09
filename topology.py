
from mininet.topo import Topo
from network_config import HOSTS, LINKS

class SmartCDN(Topo):
    def build(self):

        # Six OpenFlow switches
        s = {}
        for i in range(1, 7):
            s[i] = self.addSwitch(
                f's{i}',
                protocols='OpenFlow13', failMode='secure', dpid=f'{i:016x}'
            )

        # Four content servers
        for i in range(1, 5):
            server = self.addHost(
                f'srv{i}',
                ip=f'10.0.0.{10+i}/24',
                mac=HOSTS[f'10.0.0.{10+i}']['mac']
            )
            self.addLink(
                server, s[3 if i <= 2 else 4],
                bw=100, delay='2ms'
            )

        # Six clients
        for i in range(1, 7):
            client = self.addHost(
                f'c{i}',
                ip=f'10.0.0.{20+i}/24',
                mac=HOSTS[f'10.0.0.{20+i}']['mac']
            )
            self.addLink(
                client, s[5 if i <= 3 else 6],
                bw=100, delay='2ms'
            )

        # Main network paths
        for a, b, bandwidth in LINKS:
            self.addLink(
                s[a], s[b],
                bw=bandwidth,
                delay='5ms'
            )

topos = {'smartcdn': lambda: SmartCDN()}
