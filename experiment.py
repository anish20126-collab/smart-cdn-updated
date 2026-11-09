"""Privileged Mininet orchestration. Controller is started separately, unprivileged."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import time
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from topology import SmartCDN
from network_config import VIP
from presentation import stage, topology, verdict, show_request, snapshot, batch_summary, final_summary, say, configure, lesson, comparison_lesson, fault_banner

ROOT=Path(__file__).resolve().parent
# The same six client/file assignments are used in both modes.
MIXED_FILES=('document.pdf','image.jpg','music.mp3','video.mp4','document.pdf','image.jpg')

class Demo:
    def __init__(self,output):
        self.output=Path(output).resolve()
        self.net=Mininet(topo=SmartCDN(),controller=None,switch=OVSSwitch,link=TCLink,
                         autoStaticArp=False,build=True)
        self.net.addController('controller',controller=RemoteController,ip='127.0.0.1',port=6653)
        self.previous_servers={}
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
        stage('PART 1: IS THE NETWORK READY?',
              'Connecting all six switches and checking that all four servers answer.')
        self.net.start()
        self.wait_for(lambda:self.controller()['switches']==[1,2,3,4,5,6],20,'Six switches did not connect')
        verdict(True,'All six switches are connected to the controller')
        for i in range(1,5): self.start_server(i)
        self.spawn('c1',['telemetry_agent.py',self.output/'health.json'],'health.log')
        self.wait_for(lambda:sum(x.get('healthy',False) for x in self.health().values())==4,20,'Four servers not healthy')
        time.sleep(2)
        loss=self.net.pingAll(timeout='1')
        (self.output/'connectivity.json').write_text(json.dumps({'packet_loss_percent':loss}))
        verdict(loss==0,'Can every host reach every other host?',f'{loss}% messages lost')
        if loss: raise RuntimeError(f'Controller connectivity failed: {loss}% loss')
        snapshot(self.output)
        lesson('All six switches connected and every host could reach every other host.',
               'This is a shared setup check for BOTH modes, not a speed contest. File comparisons come next.')

    def batch(self,scenario,rounds=1,name='document.pdf',address=VIP,policy='',trial=0,case=''):
        results=[]
        mode = 'STATIC: always use srv1' if address != VIP else 'DYNAMIC: controller chooses the server'
        say(f'\nMODE: {mode}')
        say('Files: ' + (name if name else 'PDF + image + music + video, together') + '. Six clients download together.')
        if trial: say(f'Comparison trial {trial}')
        for turn in range(rounds):
            if rounds > 1: say(f"Round {turn+1} of {rounds}")
            running=[]
            for i in range(1,7):
                filename=name or MIXED_FILES[i-1]
                process=self.net[f'c{i}'].popen(['/usr/bin/python3','-B',str(ROOT/'client.py'),address,filename,
                    '--output',str(self.output/f'{scenario}-c{i}-{turn}.bin'),'--timeout','10'],
                    cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                self.processes.append(process); running.append((i,filename,process))
            deadline=time.monotonic()+30
            for i,filename,process in running:
                try:
                    stdout,stderr=process.communicate(timeout=max(.1,deadline-time.monotonic()))
                    row=json.loads(stdout.strip().splitlines()[-1])
                except (subprocess.TimeoutExpired,ValueError,IndexError) as exc:
                    process.kill(); process.communicate()
                    row=dict(ok=False,server='',client_port=0,bytes=0,response_s=0,throughput_mbps=0,error=str(exc))
                row.update(timestamp=time.time(),scenario=scenario,client=f'c{i}',content=filename,
                           policy=policy,trial=trial,case=case)
                self.rows.append(row); results.append(row)
                show_request(self.output,row,self.previous_servers)
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
        verdict(recovered,'Can a NEW download work while the fault is still present?',
                f'{self.events[-1]["recovery_s"]:.2f} seconds from fault to checked download')
        return recovered

    def paired_test(self,case,name='document.pdf',trials=1,busy=False,server_offline=False):
        """Same file and clients for both modes; report each condition separately."""
        case_rows=[]
        folder=self.output/'comparison_cases'/case
        folder.mkdir(parents=True,exist_ok=True)
        for trial in range(1,trials+1):
            policies=['static','dynamic'] if trial % 2 else ['dynamic','static']
            for policy in policies:
                stage(f'{case.upper()}: {policy.upper()} MODE — ROUND {trial} OF {trials}',
                      'Always ask srv1. No other server can be selected.' if policy=='static' else
                      'Ask the controller to choose a healthy server for each NEW request.')
                # A stopped replica is deliberately excluded from the idle condition.
                expected=3 if server_offline else 4
                self.wait_for(lambda:sum(state.get('healthy',False) for state in self.health().values())==expected
                              and all(state.get('active',0)==0 for state in self.health().values()
                                      if state.get('healthy')),20,'Healthy servers did not become idle')
                time.sleep(4)
                background=[]
                try:
                    if busy:
                        # Start an identical fresh competing workload for EACH policy batch.
                        background=self.background('10.0.0.11',12)
                        time.sleep(2)
                        say('[BUSY] 12 extra downloads are competing for srv1 right now.')
                    if server_offline and policy=='static':
                        say('srv1 is OFFLINE. Static cannot choose a replacement. Failed requests are expected here.')
                    case_rows.extend(self.batch(f'{case}-{policy}',name=name,
                        address='10.0.0.11' if policy=='static' else VIP,
                        policy=policy,trial=trial,case=case))
                finally:
                    self.stop_processes(background)
        with (folder/'requests.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(case_rows[0]))
            writer.writeheader(); writer.writerows(case_rows)
        (folder/'method.json').write_text(json.dumps(dict(case=case,trials=trials,clients=6,
            client_files={f'c{i+1}':filename for i,filename in enumerate([name]*6 if name else MIXED_FILES)},
            file_sizes={filename:(ROOT/'content'/filename).stat().st_size for filename in ([name] if name else set(MIXED_FILES))},
            static='fixed srv1 selection with SDN routing',dynamic='VIP load-aware selection',
            cooldown_seconds=4,order='alternating paired order',
            background_downloads_per_batch=12 if busy else 0,
            server_offline=server_offline,down_links=self.controller().get('down_links',[])),indent=2))
        comparison_lesson(case_rows,folder,case)
        return {policy:[row for row in case_rows if row['policy']==policy]
                for policy in ('static','dynamic')}

    def normal_delivery(self,checks,trials=1):
        stage('PART 2: NORMAL DOWNLOADS — COMPARE BOTH MODES',
              'All four file types together. Each client requests the same file in both modes.\n'
              'CHANGE means a NEW request uses another server, not that a running download moved.')
        result=self.paired_test('normal',name=None,trials=trials)
        normal=result['dynamic']
        checks['all_six_clients']=all(row['ok'] for row in normal)
        checks['normal_static_requests']=all(row['ok'] for row in result['static'])
        checks['multiple_servers']=len({row['server'] for row in normal if row['ok']})>=2
        for name in set(MIXED_FILES):
            checks[name]=all(row['ok'] for row in normal if row['content']==name)
        lesson('All four file types were included in the same batch.',
               'We do not need a separate test per file type. Both modes used the same client/file assignments.')

    def congestion(self,checks,trials=1):
        stage('PART 3: BUSY SERVER — COMPARE BOTH MODES',
              'Before EACH batch, we start 12 extra downloads from srv1.\n'
              'Watch whether choosing another server helps. The result may vary.')
        result=self.paired_test('congestion',name='document.pdf',trials=trials,busy=True)
        checks['congestion_requests']=all(row['ok'] for row in result['dynamic'])

    def server_failure(self,checks,trials=1):
        stage('PART 4: TURN OFF ONE SERVER',
              'We deliberately stop srv1. It cannot send files while it is off.\n'
              'Watch new requests use the other servers. Old broken connections must reconnect.')
        self.stop_processes([self.servers[1]])
        began=time.monotonic()
        try:
            self.wait_for(lambda:not self.health().get('10.0.0.11',{}).get('healthy',True),8,'Server failure was not detected')
            # Allow the controller's next telemetry read.
            self.wait_for(lambda:not self.controller()['health'].get('10.0.0.11',{}).get('healthy',True),5,'Controller did not observe failure')
            fault_banner('SERVER FAILED: srv1 IS OFFLINE',
                         'The server process is stopped. This is a real outage inside the virtual network.')
            snapshot(self.output)
            checks['server_recovered']=self.recovery_probe('server-failure',began)
            result=self.paired_test('server-failure',trials=trials,server_offline=True)
            checks['failed_server_avoided']=all(r['ok'] and r['server']!='srv1' for r in result['dynamic'])
            checks['static_offline_server_unavailable']=all(not row['ok'] for row in result['static'])
        finally:
            say('[RESTORING] Starting srv1 again...')
            self.start_server(1)
        self.wait_for(lambda:self.health().get('10.0.0.11',{}).get('healthy'),10,'srv1 did not restart')
        say('[RESTORED] srv1 is back ONLINE and can serve files again')
        lesson('New downloads worked without srv1.' if checks['server_recovered'] and checks['failed_server_avoided'] else 'The server-failure recovery checks did not all pass.',
               'Other healthy servers can handle NEW requests. An existing connection to a dead server must reconnect.')

    def link_failure(self,checks,trials=1):
        # Choose a link actually used by a prior service decision.
        decisions=list(csv.DictReader((self.output/'decisions.csv').open()))
        path=[int(x) for x in decisions[-1]['path'].split('-')]
        a,b=path[0:2]
        stage(f'PART 5: CLOSE THE ROAD s{a} -- s{b}',
              'This road was used by a real earlier request. We deliberately close it.\n'
              'The controller must find another road for new downloads.')
        print('Prior recorded switch route: '+' -> '.join(f's{n}' for n in path),flush=True)
        self.net.configLinkStatus(f's{a}',f's{b}','down')
        began=time.monotonic()
        try:
            self.wait_for(lambda:[a,b] in self.controller()['down_links'],8,'Link failure not detected')
            fault_banner(f'ROAD FAILED: s{a} -- s{b} IS CLOSED',
                         'This link is disabled. The controller must send traffic another way.')
            snapshot(self.output)
            checks['link_recovered']=self.recovery_probe('link-failure',began)
            result=self.paired_test('link-failure',trials=trials)
            checks['link_failure_requests']=all(row['ok'] for row in result['dynamic'])
            checks['link_static_requests']=all(row['ok'] for row in result['static'])
        finally:
            self.net.configLinkStatus(f's{a}',f's{b}','up')
        self.wait_for(lambda:[a,b] not in self.controller()['down_links'],8,'Link restoration not detected')
        say(f'[RESTORED] Road s{a} -- s{b} is OPEN again')
        lesson('New downloads worked while that road was closed.' if checks['link_recovered'] and checks['link_failure_requests'] else 'The road-failure recovery checks did not all pass.',
               'Extra network links give the controller another route. Brief packet loss is still possible.')

    def compare(self,checks,trials):
        stage('STATIC OR DYNAMIC: NORMAL NETWORK',
              'We test both modes with the same six clients and file, alternating order.')
        result=self.paired_test('comparison',trials=trials)
        for policy,rows in result.items():
            checks[f'comparison_{policy}']=all(row['ok'] for row in rows)

    def run(self,scenario,trials=1):
        checks={}
        if scenario == 'comparison':
            self.compare(checks,trials)
        else:
            self.normal_delivery(checks,trials)
            if scenario in ('all','congestion'):
                self.congestion(checks,trials)
            if scenario in ('all','server-failure'):
                self.server_failure(checks,trials)
            if scenario in ('all','link-failure'):
                self.link_failure(checks,trials)
            stage('CHECK: EVERYTHING IS BACK ON','All test faults have been removed. Let us download again.')
            restored=self.paired_test('restored',trials=trials)
            checks['restored_requests']=all(row['ok'] for row in restored['dynamic'])
            checks['restored_static_requests']=all(row['ok'] for row in restored['static'])
            lesson('Final downloads worked in both modes.' if checks['restored_requests'] and checks['restored_static_requests'] else 'Some final downloads failed.',
                   'After a fault test, restore the network and check it again.')
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
    p.add_argument('--trials',type=int,default=1,help='One static + one dynamic batch per case (default: 1)')
    p.add_argument('--present',action='store_true',help='Wait for Enter between presentation sections')
    args=p.parse_args()
    configure(args.present)
    setLogLevel('warning')
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
