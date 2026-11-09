"""Plot only actual request/port/recovery CSV records; no seeded demonstration data."""
import argparse
import csv
from collections import defaultdict,Counter
from pathlib import Path
from evaluation import summarize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def read(path):
    if not path.exists(): return []
    with path.open() as stream: return list(csv.DictReader(stream))

def plot(root):
    root=Path(root); output=root/'graphs'; output.mkdir(exist_ok=True)
    rows=read(root/'requests.csv'); groups=defaultdict(list)
    for row in rows:
        if row['ok']=='True': groups[row['scenario']].append(row)
    if groups:
        fig,axes=plt.subplots(2,1,figsize=(12,8))
        names=list(groups)
        for axis,key,label in [(axes[0],'response_s','Mean completion time (s)'),(axes[1],'throughput_mbps','Mean per-request throughput (Mbps)')]:
            axis.bar(names,[sum(float(r[key]) for r in groups[n])/len(groups[n]) for n in names])
            axis.set_ylabel(label); axis.tick_params(axis='x',rotation=30)
        fig.tight_layout(); fig.savefig(output/'performance.png'); plt.close(fig)
        distribution=Counter(r['server'] for r in rows if r['ok']=='True')
        fig,axis=plt.subplots(); axis.bar(list(distribution),list(distribution.values())); axis.set_ylabel('Successful requests'); fig.tight_layout(); fig.savefig(output/'distribution.png'); plt.close(fig)
        fig,axis=plt.subplots(figsize=(10,5))
        for scenario,records in groups.items():
            axis.scatter([r['client'] for r in records],[float(r['response_s']) for r in records],label=scenario,alpha=.7)
        axis.set_ylabel('Per-client completion time (s)'); axis.legend(fontsize=7); fig.tight_layout(); fig.savefig(output/'clients.png'); plt.close(fig)
        with (root/'summary.csv').open('w',newline='') as stream:
            writer=csv.writer(stream); writer.writerow(['scenario','successes','failures','mean_response_s','mean_throughput_mbps'])
            for name,records in groups.items():
                writer.writerow([name,len(records),sum(r['scenario']==name and r['ok']!='True' for r in rows),sum(float(r['response_s']) for r in records)/len(records),sum(float(r['throughput_mbps']) for r in records)/len(records)])
    summaries, comparison_distribution = summarize(rows,root)
    if summaries:
        fig,axes=plt.subplots(1,2,figsize=(10,4))
        for axis,metric,label in [(axes[0],'response_s','Transfer time (s)'),
                                  (axes[1],'throughput_mbps','Per-request throughput (Mbps)')]:
            measured=[row for row in summaries if row['mean_'+metric] != '']
            axis.bar([row['policy'] for row in measured],
                     [row['mean_'+metric] for row in measured],
                     yerr=[row['std_'+metric] for row in measured],capsize=5)
            axis.set_ylabel(label)
        fig.suptitle('Static vs dynamic: trial means; error bars = sample standard deviation')
        fig.tight_layout(); fig.savefig(output/'comparison.png'); plt.close(fig)
        fig,axis=plt.subplots()
        servers=['srv1','srv2','srv3','srv4']
        for index,policy in enumerate(['static','dynamic']):
            axis.bar([x+index*.4 for x in range(4)],
                     [comparison_distribution[policy,server] for server in servers],
                     width=.4,label=policy)
        axis.set_xticks([x+.2 for x in range(4)],servers)
        axis.set_ylabel('Successful comparison requests'); axis.legend()
        fig.tight_layout(); fig.savefig(output/'comparison_distribution.png'); plt.close(fig)
    ports=read(root/'ports.csv')
    if ports:
        series=defaultdict(list); start=min(float(r['timestamp']) for r in ports)
        for row in ports:
            if float(row['capacity_mbps'])<100:
                series[f's{row["switch"]}/p{row["port"]}'].append((float(row['timestamp'])-start,float(row['tx_mbps'])))
        fig,axis=plt.subplots(figsize=(12,6))
        for name,values in series.items():
            axis.plot(*zip(*values),label=name)
        axis.set(xlabel='Elapsed time (s)',ylabel='Measured TX Mbps'); axis.legend(ncol=3,fontsize=7); fig.tight_layout(); fig.savefig(output/'links.png'); plt.close(fig)
    recovery=read(root/'recovery.csv')
    if recovery:
        fig,axis=plt.subplots(); axis.bar([r['scenario'] for r in recovery],[float(r['recovery_s']) for r in recovery]); axis.set_ylabel('Time to successful new transfer (s)'); fig.tight_layout(); fig.savefig(output/'recovery.png'); plt.close(fig)
    print(f'Graphs from measured CSV data: {output}')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('results'); plot(p.parse_args().results)
