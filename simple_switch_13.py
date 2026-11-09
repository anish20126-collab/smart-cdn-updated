"""Loop-free IPv4 controller with proxy ARP and per-connection VIP steering.

The fixed lab topology supplies adjacency; OpenFlow port state supplies failures.
No broadcast frames are flooded. All host IPv4 paths are computed centrally.
"""
import csv
import json
import os
from pathlib import Path
import time
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, arp, ipv4, tcp, ether_types
from network_config import HOSTS, SERVERS, VIP, VMAC, LINK_PORTS
from routing import shortest_path, select_server

COOKIE = 0x5343444e

class SimpleSwitch13(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.datapaths = {}
        self.down_ports = set()
        self.rates = {}
        self.previous = {}
        self.sessions = {}
        self.health = {}
        self.decisions = 0
        self.output = Path(os.environ.get('SMARTCDN_RESULTS','results/live'))
        self.output.mkdir(parents=True,exist_ok=True)
        self.telemetry = Path(os.environ.get('SMARTCDN_HEALTH',str(self.output/'health.json')))
        self.worker = hub.spawn(self.monitor)

    def record(self,name,row):
        path = self.output/(name+'.csv')
        exists = path.exists() and path.stat().st_size>0
        with path.open('a',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=list(row))
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    def add_flow(self,dp,match,actions,priority=10,idle=30):
        p,o = dp.ofproto_parser,dp.ofproto
        dp.send_msg(p.OFPFlowMod(datapath=dp,cookie=COOKIE,priority=priority,
            idle_timeout=idle,match=p.OFPMatch(**match),
            instructions=[p.OFPInstructionActions(o.OFPIT_APPLY_ACTIONS,actions)]))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures,CONFIG_DISPATCHER)
    def features(self,ev):
        dp=ev.msg.datapath
        self.datapaths[dp.id]=dp
        p,o=dp.ofproto_parser,dp.ofproto
        self.add_flow(dp,{},[p.OFPActionOutput(o.OFPP_CONTROLLER,o.OFPCML_NO_BUFFER)],0,0)
        dp.send_msg(p.OFPPortDescStatsRequest(dp,0))
        self.logger.info('Switch s%s connected with OpenFlow 1.3',dp.id)
        self.invalidate()

    @set_ev_cls(ofp_event.EventOFPStateChange,[MAIN_DISPATCHER,DEAD_DISPATCHER])
    def state(self,ev):
        if ev.state==DEAD_DISPATCHER:
            self.datapaths.pop(ev.datapath.id,None)
            self.invalidate()

    def down_links(self):
        return {(a,b) for (a,b),(port,_) in LINK_PORTS.items()
                if (a,port) in self.down_ports or (b,LINK_PORTS[b,a][0]) in self.down_ports
                or a not in self.datapaths or b not in self.datapaths}

    def invalidate(self):
        for dp in list(self.datapaths.values()):
            p,o=dp.ofproto_parser,dp.ofproto
            # Preserve only priority-zero table miss; all application routes are recomputed.
            dp.send_msg(p.OFPFlowMod(datapath=dp,cookie=COOKIE,cookie_mask=0xffffffffffffffff,
                command=o.OFPFC_DELETE,out_port=o.OFPP_ANY,out_group=o.OFPG_ANY,
                match=p.OFPMatch()))
            self.add_flow(dp,{},[p.OFPActionOutput(o.OFPP_CONTROLLER,o.OFPCML_NO_BUFFER)],0,0)

    def update_port(self,dp,desc):
        key=(dp.id,desc.port_no)
        down=bool(desc.state & dp.ofproto.OFPPS_LINK_DOWN or desc.config & dp.ofproto.OFPPC_PORT_DOWN)
        old=key in self.down_ports
        if down:
            self.down_ports.add(key)
        else:
            self.down_ports.discard(key)
        return old!=down

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply,MAIN_DISPATCHER)
    def descriptions(self,ev):
        changed=False
        for desc in ev.msg.body:
            changed=self.update_port(ev.msg.datapath,desc) or changed
        if changed:
            self.invalidate()

    @set_ev_cls(ofp_event.EventOFPPortStatus,MAIN_DISPATCHER)
    def port_status(self,ev):
        if self.update_port(ev.msg.datapath,ev.msg.desc):
            self.logger.warning('Port state changed s%s/%s; recomputing paths',ev.msg.datapath.id,ev.msg.desc.port_no)
            self.record('events',dict(timestamp=time.time(),event='port_change',switch=ev.msg.datapath.id,port=ev.msg.desc.port_no))
            self.invalidate()

    def monitor(self):
        while self.is_active:
            try:
                status=json.loads(self.telemetry.read_text())
                self.health=status.get('servers',{}) if time.time()-status['timestamp']<4 else {}
            except (OSError,ValueError,KeyError):
                self.health={}
            now=time.monotonic()
            self.sessions={k:v for k,v in self.sessions.items() if now-v['seen']<300}
            for dp in list(self.datapaths.values()):
                p,o=dp.ofproto_parser,dp.ofproto
                dp.send_msg(p.OFPPortStatsRequest(dp,0,o.OFPP_ANY))
                dp.send_msg(p.OFPFlowStatsRequest(dp))
            path=self.output/'controller.json'
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(timestamp=time.time(),switches=sorted(self.datapaths),
                down_links=sorted(self.down_links()),health=self.health,decisions=self.decisions)))
            temporary.replace(path)
            hub.sleep(1)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply,MAIN_DISPATCHER)
    def port_stats(self,ev):
        now=time.monotonic()
        for stat in ev.msg.body:
            if stat.port_no>=ev.msg.datapath.ofproto.OFPP_MAX:
                continue
            key=(ev.msg.datapath.id,stat.port_no)
            previous=self.previous.get(key)
            self.previous[key]=(now,stat.tx_bytes,stat.rx_bytes)
            if not previous or now<=previous[0]:
                continue
            seconds=now-previous[0]
            tx=max(0,stat.tx_bytes-previous[1])*8/1e6/seconds
            rx=max(0,stat.rx_bytes-previous[2])*8/1e6/seconds
            self.rates[key]=tx
            capacity=next((bw for (a,b),(port,bw) in LINK_PORTS.items() if a==key[0] and port==key[1]),100)
            self.record('ports',dict(timestamp=time.time(),switch=key[0],port=key[1],tx_mbps=tx,
                rx_mbps=rx,capacity_mbps=capacity,utilization=tx/capacity))
            if tx/capacity>.7:
                self.logger.info('Congestion s%s/%s: %.2f/%.0f Mbps',*key,tx,capacity)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply,MAIN_DISPATCHER)
    def flow_stats(self,ev):
        for flow in ev.msg.body:
            if flow.cookie==COOKIE and flow.priority:
                self.record('flows',dict(timestamp=time.time(),switch=ev.msg.datapath.id,
                    priority=flow.priority,packets=flow.packet_count,bytes=flow.byte_count,
                    duration_s=flow.duration_sec,match=str(flow.match)))

    def emit(self,dp,port,data):
        p,o=dp.ofproto_parser,dp.ofproto
        dp.send_msg(p.OFPPacketOut(datapath=dp,buffer_id=o.OFP_NO_BUFFER,in_port=o.OFPP_CONTROLLER,
            actions=[p.OFPActionOutput(port)],data=data))

    def proxy_arp(self,msg,eth,request):
        if request.opcode!=arp.ARP_REQUEST:
            return
        mac=VMAC if request.dst_ip==VIP else HOSTS.get(request.dst_ip,{}).get('mac')
        if not mac:
            return
        reply=packet.Packet()
        reply.add_protocol(ethernet.ethernet(dst=eth.src,src=mac,ethertype=ether_types.ETH_TYPE_ARP))
        reply.add_protocol(arp.arp(opcode=arp.ARP_REPLY,src_mac=mac,src_ip=request.dst_ip,
            dst_mac=request.src_mac,dst_ip=request.src_ip))
        reply.serialize()
        self.emit(msg.datapath,msg.match['in_port'],reply.data)

    def path_rules(self,source,destination,match,priority=10,first=None,last=None):
        _,path=shortest_path(HOSTS[source]['switch'],HOSTS[destination]['switch'],self.down_links(),self.rates)
        if not path:
            return {}
        actions_by_switch={}
        for index,node in reversed(list(enumerate(path))):
            dp=self.datapaths.get(node)
            if not dp:
                return {}
            p=dp.ofproto_parser
            port=HOSTS[destination]['port'] if index==len(path)-1 else LINK_PORTS[node,path[index+1]][0]
            actions=[]
            if index==0 and first:
                actions.extend(p.OFPActionSetField(**{k:v}) for k,v in first.items())
            if index==len(path)-1:
                actions.append(p.OFPActionSetField(eth_dst=HOSTS[destination]['mac']))
                if last:
                    actions.extend(p.OFPActionSetField(**{k:v}) for k,v in last.items())
            actions.append(p.OFPActionOutput(port))
            self.add_flow(dp,match,actions,priority,30)
            actions_by_switch[node]=actions
        return actions_by_switch

    def service_rules(self,client,client_port,session):
        server=session['server']
        common=dict(eth_type=0x800,ip_proto=6)
        forward=dict(common,ipv4_src=client,ipv4_dst=server,tcp_src=client_port,tcp_dst=5000)
        actions=self.path_rules(client,server,forward,100)
        reverse=dict(common,ipv4_src=server,ipv4_dst=client,tcp_src=5000,tcp_dst=client_port)
        reverse_actions=self.path_rules(server,client,reverse,100,last=dict(ipv4_src=VIP,eth_src=VMAC))
        # VIP rewrite only at client ingress. Intermediate matches see the physical address.
        ingress=HOSTS[client]['switch']
        if ingress not in actions:
            return {},{}
        dp=self.datapaths[ingress]
        p=dp.ofproto_parser
        translated=[p.OFPActionSetField(ipv4_dst=server),p.OFPActionSetField(eth_dst=HOSTS[server]['mac'])]+actions[ingress]
        self.add_flow(dp,dict(common,ipv4_src=client,ipv4_dst=VIP,tcp_src=client_port,tcp_dst=5000),translated,110,30)
        actions[ingress]=translated
        return actions,reverse_actions

    @set_ev_cls(ofp_event.EventOFPPacketIn,MAIN_DISPATCHER)
    def packet_in(self,ev):
        msg=ev.msg
        pkt=packet.Packet(msg.data)
        eth=pkt.get_protocol(ethernet.ethernet)
        if not eth:
            return
        request=pkt.get_protocol(arp.arp)
        if request:
            self.proxy_arp(msg,eth,request)
            return
        ip=pkt.get_protocol(ipv4.ipv4)
        if not ip or ip.src not in HOSTS:
            return
        segment=pkt.get_protocol(tcp.tcp)
        actions={}
        if segment and ip.dst==VIP and segment.dst_port==5000:
            key=(ip.src,segment.src_port)
            session=self.sessions.get(key)
            new_syn=bool(segment.bits & tcp.TCP_SYN and not segment.bits & tcp.TCP_ACK)
            if session and new_syn and session['seq']!=segment.seq:
                session=None
            if not session:
                if not new_syn:
                    return
                reservations={server:sum(1 for value in self.sessions.values()
                    if value['server']==server and time.monotonic()-value['created']<2) for server in SERVERS}
                selected=select_server(ip.src,self.health,self.down_links(),self.rates,reservations)
                if not selected:
                    self.logger.warning('No healthy reachable server for %s',ip.src)
                    return
                score,server,path=selected
                session=dict(server=server,seen=time.monotonic(),created=time.monotonic(),seq=segment.seq)
                self.sessions[key]=session
                self.decisions+=1
                self.record('decisions',dict(timestamp=time.time(),client=ip.src,client_port=segment.src_port,
                    server=server,score=score,path='-'.join(map(str,path)),
                    active=self.health[server].get('active',0),mbps=self.health[server].get('mbps',0)))
                self.logger.info('SELECT %s:%s -> %s score=%.2f path=%s',*key,server,score,path)
            session['seen']=time.monotonic()
            actions,_=self.service_rules(*key,session)
        elif segment and ip.src in SERVERS and (ip.dst,segment.dst_port) in self.sessions:
            key=(ip.dst,segment.dst_port)
            session=self.sessions[key]
            if session['server']!=ip.src:
                return
            session['seen']=time.monotonic()
            _,actions=self.service_rules(*key,session)
        elif ip.dst in HOSTS:
            actions=self.path_rules(ip.src,ip.dst,dict(eth_type=0x800,ipv4_src=ip.src,ipv4_dst=ip.dst))
        selected=actions.get(msg.datapath.id)
        if selected:
            p,o=msg.datapath.ofproto_parser,msg.datapath.ofproto
            msg.datapath.send_msg(p.OFPPacketOut(datapath=msg.datapath,buffer_id=o.OFP_NO_BUFFER,
                in_port=msg.match['in_port'],actions=selected,data=msg.data))
