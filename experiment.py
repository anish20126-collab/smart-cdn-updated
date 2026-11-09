"""Privileged Mininet orchestration. Controller is started separately, unprivileged."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from topology import SmartCDN
from network_config import VIP
from presentation import stage, topology, verdict, show_request, snapshot, batch_summary, final_summary

ROOT=Path(__file__).resolve().parent

class Demo:
    def __init__(self,output):
        self.output=Path(output).resolve()
        self.net=Mininet(topo=SmartCDN(),controller=None,switch=OVSSwitch,link=TCLink,
                         autoStaticArp=False,build=True)
        self.net.addController('controller',controller=RemoteController,ip='127.0.0.1',port=6653)
        self.processes=[]; self.handles=[]; self.servers={}; self.rows=[]; self.events=[]

    def spawn(self,host,args,log):
        stream=(self.output/log).open('w'); self.handles.append(stream)
        process=self.net[host].popen(['/usr/bin/python3','-B',*map(str,args)],cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process

    def start_server(self,i):
        # Optional pacing keeps concurrent transfers observable on small VM labs.
        self.servers[i]=self.spawn(f'srv{i}',['server.py',f'srv{i}','--root',ROOT/'content'],f'srv{i}.log')

    def wait_for(self,predicate,seconds,message):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            try:
                if predicate(): return
            except (OSError,ValueError,KeyError): pass
            time.sleep(.3)
        raise RuntimeError(message)

    def controller(self):
        return json.loads((self.output/'controller.json').read_text())

    def health(self):
        value=json.loads((self.output/'health.json').read_text())
        return value['servers'] if time.time()-value['timestamp']<4 else {}

    def start(self):
        topology()
        stage('1. CONTROLLER AND CONNECTIVITY',
              'Waiting for six OpenFlow connections and four healthy content servers.')
        self.net.start()
        self.wait_for(lambda:self.controller()['switches']==[1,2,3,4,5,6],20,'Six switches did not connect')
        verdict(True,'All six switches connected to OS-Ken over OpenFlow 1.3')
        for i in range(1,5): self.start_server(i)
        self.spawn('c1',['telemetry_agent.py',self.output/'health.json'],'health.log')
        self.wait_for(lambda:sum(x.get('healthy',False) for x in self.health().values())==4,20,'Four servers not healthy')
        time.sleep(2)
        loss=self.net.pingAll(timeout='1')
        (self.output/'connectivity.json').write_text(json.dumps({'packet_loss_percent':loss}))
        verdict(loss==0,'Controller-managed connectivity',f'{loss}% ping loss; zero loss required')
        if loss: raise RuntimeError(f'Controller connectivity failed: {loss}% loss')
        snapshot(self.output)

    def batch(self,scenario,rounds=1,name='document.pdf',address=VIP,policy='',trial=0):
        results=[]
        print(f'\nREQUESTS: {scenario} | {rounds} round(s), 6 simultaneous clients per round | {name} -> {address}',flush=True)
        for turn in range(rounds):
            running=[]
            for i in range(1,7):
                process=self.net[f'c{i}'].popen(['/usr/bin/python3','-B',str(ROOT/'client.py'),address,name,
                    '--output',str(self.output/f'{scenario}-c{i}-{turn}.bin'),'--timeout','25'],
                    cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                self.processes.append(process); running.append((i,process))
            for i,process in running:
                try:
                    stdout,stderr=process.communicate(timeout=40)
                    row=json.loads(stdout.strip().splitlines()[-1])
                except (subprocess.TimeoutExpired,ValueError,IndexError) as exc:
                    process.kill(); process.communicate()
                    row=dict(ok=False,server='',client_port=0,bytes=0,response_s=0,throughput_mbps=0,error=str(exc))
                row.update(timestamp=time.time(),scenario=scenario,client=f'c{i}',content=name,
                           policy=policy,trial=trial)
                self.rows.append(row); results.append(row)
                show_request(self.output,row)
            self.save()
        batch_summary(results)
        return results

    def save(self):
        for filename,rows in [('requests.csv',self.rows),('recovery.csv',self.events)]:
            if rows:
                with (self.output/filename).open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

    def background(self,address,number=8):
        return [self.spawn(f'c{j%6+1}',['client.py',address,'video.mp4','--timeout','40'],f'background-{time.time_ns()}.log') for j in range(number)]

    @staticmethod
    def stop_processes(processes):
        for process in processes:
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()

    def recovery_probe(self,scenario,started,timeout=20):
        deadline=time.monotonic()+timeout
        recovered=False
        while time.monotonic()<deadline:
            process=self.net['c2'].popen(['/usr/bin/python3','-B',str(ROOT/'client.py'),VIP,'image.jpg','--timeout','2'],
                cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            self.processes.append(process)
            try:
                stdout,_=process.communicate(timeout=4)
                recovered=json.loads(stdout.strip().splitlines()[-1]).get('ok',False)
            except (ValueError,IndexError,subprocess.TimeoutExpired):
                process.kill(); process.communicate()
            if recovered: break
            time.sleep(.25)
        self.events.append(dict(timestamp=time.time(),scenario=scenario,recovered=recovered,
                                recovery_s=time.monotonic()-started))
        self.save()
        verdict(recovered,f'{scenario}: new connection recovery',
                f'{self.events[-1]["recovery_s"]:.3f} s from fault to verified transfer (includes detection and download)')
        return recovered

    def normal_delivery(self,checks):
        stage('2. NORMAL CONTENT DELIVERY AND LOAD DISTRIBUTION',
              'All clients use one VIP. The controller chooses replicas and installs TCP-specific forwarding rules.')
        normal=self.batch('normal',3)
        checks['all_six_clients']=all(r['ok'] for r in normal)
        checks['multiple_servers']=len({r['server'] for r in normal if r['ok']})>=2
        # Exercise every sample type; video also provides sustained measurable load.
        for name in ['image.jpg','music.mp3','video.mp4']:
            checks[name]=all(r['ok'] for r in self.batch('content-'+name,name=name))

    def congestion(self,checks):
        stage('3. CONGESTION AND SERVER LOAD',
              'Starting 12 real video downloads to srv1, then concurrent VIP requests.\n'
              'Compare measured load, chosen routes and transfer time; successful requests alone do not prove congestion avoidance.')
        # Saturate the existing TCLink bottlenecks without changing their capacities.
        background=self.background('10.0.0.11',12)
        time.sleep(2)
        snapshot(self.output)
        try:
            loaded=self.batch('congestion',2,name='music.mp3')
            checks['congestion_requests']=all(r['ok'] for r in loaded)
        finally:
            self.stop_processes(background)

        time.sleep(2)

    def server_failure(self,checks):
        stage('4. SERVER FAILURE: STOP srv1 (10.0.0.11)',
              'Intentional fault: srv1 will stop answering. PASS requires new requests to healthy replicas, not srv1.\n'
              'Connections to the stopped server must reconnect; they are not migrated.')
        self.stop_processes([self.servers[1]])
        began=time.monotonic()
        try:
            self.wait_for(lambda:not self.health().get('10.0.0.11',{}).get('healthy',True),8,'Server failure was not detected')
            # Allow the controller's next telemetry read.
            self.wait_for(lambda:not self.controller()['health'].get('10.0.0.11',{}).get('healthy',True),5,'Controller did not observe failure')
            verdict(True,'Health probe and controller both detected srv1 unavailable')
            snapshot(self.output)
            checks['server_recovered']=self.recovery_probe('server-failure',began)
            rows=self.batch('server-failure',2)
            checks['failed_server_avoided']=all(r['ok'] and r['server']!='srv1' for r in rows)
        finally:
            self.start_server(1)
        self.wait_for(lambda:self.health().get('10.0.0.11',{}).get('healthy'),10,'srv1 did not restart')
        verdict(True,'srv1 restored and health probe successful')

    def link_failure(self,checks):
        # Choose a link actually used by a prior service decision.
        decisions=list(csv.DictReader((self.output/'decisions.csv').open()))
        path=[int(x) for x in decisions[-1]['path'].split('-')]
        a,b=path[0:2]
        stage(f'5. PATH FAILURE: DISABLE s{a}--s{b}',
              'Intentional fault on a link from a recorded service route.\n'
              'Port-status detection removes stale routes; new forwarding must avoid this link.')
        print('Prior recorded switch route: '+' -> '.join(f's{n}' for n in path),flush=True)
        self.net.configLinkStatus(f's{a}',f's{b}','down')
        began=time.monotonic()
        try:
            self.wait_for(lambda:[a,b] in self.controller()['down_links'],8,'Link failure not detected')
            verdict(True,f'Controller detected s{a}--s{b} down; application routes invalidated')
            snapshot(self.output)
            checks['link_recovered']=self.recovery_probe('link-failure',began)
            checks['link_failure_requests']=all(r['ok'] for r in self.batch('link-failure',2))
        finally:
            self.net.configLinkStatus(f's{a}',f's{b}','up')
        self.wait_for(lambda:[a,b] not in self.controller()['down_links'],8,'Link restoration not detected')
        verdict(True,f'Link s{a}--s{b} restored')

    def compare(self,checks,trials):
        """Paired trials: fixed srv1 versus load-aware VIP, with equal workload."""
        stage('STATIC VS DYNAMIC COMPARISON',
              'Same six clients and document.pdf. Static uses srv1; dynamic uses the VIP.\n'
              'Each trial runs both policies; the order alternates to reduce order bias.')
        workload = {'static': '10.0.0.11', 'dynamic': VIP}
        metadata = dict(trials=trials,clients=6,file='document.pdf',
                        file_bytes=(ROOT/'content/document.pdf').stat().st_size,
                        static_server='srv1',dynamic_address=VIP,
                        topology='unchanged six-switch topology',
                        background_traffic='health probes only',
                        cooldown_seconds=4,order='alternating paired trials',
                        static_definition='fixed server selection, controller-managed IP routing')
        (self.output/'comparison_method.json').write_text(json.dumps(metadata,indent=2))
        for trial in range(1,trials+1):
            policies = ['static','dynamic'] if trial % 2 else ['dynamic','static']
            for policy in policies:
                # Wait for real transfers to stop, then let telemetry and reservations settle.
                self.wait_for(lambda:len(self.health())==4 and all(
                    state.get('healthy') and state.get('active',0)==0
                    for state in self.health().values()),20,'Servers did not become idle')
                time.sleep(4)
                rows=self.batch(f'comparison-{policy}',address=workload[policy],
                                policy=policy,trial=trial)
                checks[f'comparison_{policy}_trial_{trial}']=all(row['ok'] for row in rows)

    def run(self,scenario,trials=3):
        checks={}
        if scenario == 'comparison':
            self.compare(checks,trials)
        else:
            self.normal_delivery(checks)
            if scenario in ('all','congestion'):
                self.congestion(checks)
            if scenario in ('all','server-failure'):
                self.server_failure(checks)
            if scenario in ('all','link-failure'):
                self.link_failure(checks)
            stage('RESTORED NETWORK','Verified requests after restoring experimental faults.')
            checks['restored_requests']=all(row['ok'] for row in self.batch('restored'))
            if scenario == 'all':
                self.compare(checks,trials)
        (self.output/'acceptance.json').write_text(json.dumps(checks,indent=2))
        final_summary(checks,self.output)
        return all(checks.values())

    def close(self):
        self.stop_processes(self.processes)
        self.net.stop()
        for stream in self.handles: stream.close()
        self.save()

def main():
    p=argparse.ArgumentParser(); p.add_argument('--results',required=True)
    p.add_argument('--scenario',choices=['all','normal','congestion','server-failure','link-failure','comparison','cli'],default='all')
    p.add_argument('--trials',type=int,default=3,help='Paired static/dynamic trials (default: 3)')
    args=p.parse_args()
    if args.trials < 1: p.error('--trials must be at least 1')
    if os.geteuid()!=0: p.error('Run this Mininet process with sudo; controller stays unprivileged')
    demo=Demo(args.results)
    try:
        demo.start()
        if args.scenario=='cli': CLI(demo.net); ok=True
        else: ok=demo.run(args.scenario,args.trials)
    except Exception as exc:
        verdict(False,'Demo could not finish',str(exc))
        print(f'Inspect {demo.output}/controller.log and server logs for the cause.',flush=True)
        raise
    finally:
        demo.close()
        # Return result ownership to the invoking user after the privileged portion.
        uid=int(os.environ.get('SUDO_UID',os.getuid())); gid=int(os.environ.get('SUDO_GID',os.getgid()))
        for path in demo.output.rglob('*'): os.chown(path,uid,gid)
    raise SystemExit(0 if ok else 1)

if __name__=='__main__': main()
