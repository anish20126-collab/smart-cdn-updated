"""Summarize real paired trials. No measurements are generated here."""
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev


def summarize(rows, root):
    groups = defaultdict(list)
    for row in rows:
        if row.get('policy') in ('static', 'dynamic'):
            groups[row['policy'], int(row['trial'])].append(row)
    trials = []
    for (policy, trial), records in sorted(groups.items()):
        successful = [row for row in records if str(row['ok']) == 'True']
        trials.append(dict(policy=policy, trial=trial, successes=len(successful),
            failures=len(records)-len(successful),
            mean_response_s=mean(float(row['response_s']) for row in successful) if successful else '',
            mean_throughput_mbps=mean(float(row['throughput_mbps']) for row in successful) if successful else ''))
    summaries = []
    for policy in ('static', 'dynamic'):
        selected = [row for row in trials if row['policy'] == policy]
        if not selected:
            continue
        summary = dict(policy=policy, trials=len(selected),
            successes=sum(row['successes'] for row in selected),
            failures=sum(row['failures'] for row in selected))
        for metric in ('response_s', 'throughput_mbps'):
            values = [row['mean_'+metric] for row in selected if row['successes']]
            summary['mean_'+metric] = mean(values) if values else ''
            summary['std_'+metric] = stdev(values) if len(values)>1 else (0 if values else '')
        summaries.append(summary)
    distribution = Counter((row['policy'], row['server']) for row in rows
                           if row.get('policy') in ('static','dynamic') and str(row['ok'])=='True')
    tables = {'comparison_trials.csv': trials, 'comparison_summary.csv': summaries,
              'comparison_distribution.csv': [dict(policy=policy,server=server,requests=count)
                  for (policy,server),count in sorted(distribution.items())]}
    for name, records in tables.items():
        if records:
            with (Path(root)/name).open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(records[0]))
                writer.writeheader(); writer.writerows(records)
    return summaries, distribution
