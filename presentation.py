"""Readable demo narration. Every outcome and route comes from this run's data."""
import json
from collections import Counter
from pathlib import Path
import sys
from network_config import HOSTS


def say(message=''):
    print(message, flush=True)


# Presentation mode pauses between sections, not between individual downloads.
PRESENT = False
STARTED = False


def configure(present=False):
    global PRESENT, STARTED
    PRESENT = present and sys.stdin.isatty()
    STARTED = False


def stage(title, explanation):
    global STARTED
    if PRESENT and STARTED:
        input('\nPress Enter when you are ready for the next part... ')
    STARTED = True
    say('\n' + '=' * 66)
    say(title)
    say(explanation)
    say('=' * 66)


def topology():
    stage('OUR NETWORK: 6 CLIENTS, 6 SWITCHES, 4 FILE SERVERS',
          'Clients ask for files. Servers store files. Switches are the roads.\n'
          'The controller is the traffic guide: it tells the switches where to send data.')
    say("""
    Clients c1,c2,c3 -- s5             s3 -- Servers srv1,srv2
    Clients c4,c5,c6 -- s6             s4 -- Servers srv3,srv4

    Exact switch connections (roads):
      s1: s2, s3, s4       s2: s1, s5, s6
      s3: s1, s4, s5       s4: s1, s3, s6
      s5: s2, s3, s6       s6: s2, s4, s5

    Extra roads let us go another way when one road is closed.
    One service address for dynamic requests: 10.0.0.100
    [FAULT] something went down   [FAIL] a task did not work
    [PASS] a task worked          [CHANGE] a new request used a different server
""")


def verdict(passed, title, detail=''):
    say(f'[{"PASS" if passed else "FAIL"}] {title}' + (f' | {detail}' if detail else ''))


def show_request(output, row, previous_servers=None):
    client = row['client']
    if not row['ok']:
        say('>>> DOWNLOAD FAILED <<<')
        verdict(False, f"{client} could not get {row['content']}",
                row.get('error') or 'The download did not finish')
        return
    server = row['server']
    # Compare successful NEW requests, never imply a running TCP connection moved.
    if previous_servers is not None and row.get('policy') != 'static':
        previous = previous_servers.get(client)
        if previous and previous != server:
            say(f'[CHANGE] {client}: {previous} -> {server} for this NEW request')
        previous_servers[client] = server
    say(f"[PASS] {client} <- {server} | {row['content']} | file checked OK | {row['response_s']:.2f} seconds")


def snapshot(output):
    try:
        state = json.loads((Path(output)/'controller.json').read_text())
        healthy = []
        for ip, health in sorted(state.get('health', {}).items()):
            name = HOSTS.get(ip, {}).get('name', ip)
            if health.get('healthy'):
                healthy.append(name)
            else:
                say(f'[FAULT] {name} is OFFLINE. New requests cannot use it.')
        say('Available servers: ' + (', '.join(healthy) or 'none'))
        down = sorted({tuple(sorted(pair)) for pair in state.get('down_links', [])})
        for a, b in down:
            say(f'[FAULT] Road s{a} -- s{b} is CLOSED.')
        if not down:
            say('All switch roads are open.')
    except (OSError, ValueError, KeyError, TypeError):
        say('Still waiting for a network update.')


def batch_summary(rows):
    successful=[row for row in rows if row['ok']]
    count=Counter(row['server'] for row in successful)
    say(f'Downloads finished correctly: {len(successful)} out of {len(rows)}. Files served: '
        + ', '.join(f'{server}={number}' for server,number in sorted(count.items())))
    if successful:
        say(f'Mean completion time: {sum(row["response_s"] for row in successful)/len(successful):.3f} s')


CHECKS = {
    'all_six_clients': 'Every baseline request from all six clients completed and passed SHA-256',
    'multiple_servers': 'Baseline requests used at least two different servers',
    'image.jpg': 'All six clients received image.jpg correctly',
    'music.mp3': 'All six clients received music.mp3 correctly',
    'video.mp4': 'All six clients received video.mp4 correctly',
    'congestion_requests': 'VIP requests completed while competing TCP transfers were running',
    'server_recovered': 'Download a checked file while srv1 is offline',
    'failed_server_avoided': 'Serve all new requests without using offline srv1',
    'link_recovered': 'Download a checked file while a switch road is closed',
    'link_failure_requests': 'Complete all downloads while a switch road is closed',
    'restored_requests': 'All six clients completed requests after the experiments',
}


def final_summary(checks, output):
    stage('FINISHED: WHAT WORKED?', 'A server or road can fail while the recovery test still PASSES.')
    passed = sum(bool(value) for value in checks.values())
    verdict(passed == len(checks), f'{passed} out of {len(checks)} checks worked')
    for key, value in checks.items():
        if value:
            continue
        label = CHECKS.get(key,key)
        if key.startswith('comparison_'):
            label = key.replace('_',' ').upper()
        verdict(False,label)
    say(f'\nEvidence and CSV files: {output}')
    say('Full check-by-check results: acceptance.json in that folder.')


def lesson(observed, explanation):
    say('\nWHAT WE LEARNED')
    say('  This test: ' + observed)
    say('  Remember: ' + explanation)


def fault_banner(title, explanation):
    border = '!' * 66
    text = f'\n{border}\n!!! [FAULT] {title} !!!\n{explanation}\nThe fault is STILL PRESENT during the following downloads.\n{border}'
    if sys.stdout.isatty():
        text = '\033[1;31m' + text + '\033[0m'
    say(text)


def comparison_lesson(rows, output, case='comparison'):
    from evaluation import summarize
    summaries, distribution = summarize(rows, output)
    by_policy = {row['policy']: row for row in summaries}
    say('\n' + '-' * 66)
    say('RESULT: ' + case.upper() + ' — STATIC vs DYNAMIC')
    for result in summaries:
        timing = ('no successful downloads' if result['mean_response_s'] == '' else
                  f"{result['mean_response_s']:.2f} seconds/file; {result['mean_throughput_mbps']:.2f} Mbps")
        say(f"  {result['policy'].upper():7} {result['successes']} worked / {result['failures']} failed | {timing}")
        servers = [f'{server}={count}' for (policy,server),count in sorted(distribution.items())
                   if policy == result['policy']]
        say('          Files from: ' + (', '.join(servers) or 'no server'))
    static, dynamic = by_policy.get('static'), by_policy.get('dynamic')
    if not static or not dynamic:
        lesson('A mode has no records. No fair comparison is available.', 'Run both modes under the same conditions.')
        return
    difference = dynamic['successes'] - static['successes']
    if difference:
        better = 'DYNAMIC' if difference > 0 else 'STATIC'
        say(f'  MORE FILES DELIVERED: {better} ({abs(difference)} more).')
    else:
        say('  FILES DELIVERED: TIE. Both delivered the same number.')
    faster = None
    if static['mean_response_s'] != '' and dynamic['mean_response_s'] != '':
        delta = dynamic['mean_response_s'] - static['mean_response_s']
        if abs(delta) < .005:
            say('  SPEED: About the same in this run.')
        else:
            faster = 'STATIC' if delta > 0 else 'DYNAMIC'
            say(f'  FASTER SUCCESSFUL DOWNLOADS: {faster}, by {abs(delta):.2f} seconds/file on average.')
        if static['failures'] or dynamic['failures']:
            say('  Caution: timing excludes failures. Faster does not mean more reliable.')
    else:
        say('  SPEED: Cannot compare — one mode had no successful download.')
    say('\nWHY / WHAT WE LEARNED')
    if case == 'server-failure':
        if not static['successes'] and dynamic['successes']:
            say('  OBSERVED: srv1 was stopped. Static had no working replacement; dynamic used other servers.')
        else:
            say('  Check the counts: the server-outage test did not show the expected simple pattern.')
        say('  Static is tied to srv1. Dynamic can choose a healthy replacement for NEW connections.')
    elif case == 'link-failure':
        say('  Both modes use SDN routing, so BOTH can take another road after a link fails.')
        say('  Static fixes the SERVER, not the road. This is not a comparison against frozen routes.')
    elif case == 'congestion':
        say('  Both modes faced fresh extra traffic to srv1 before each batch.')
        used = {server for (policy,server),count in distribution.items() if policy == 'dynamic' and count}
        say('  OBSERVED: dynamic used ' + (', '.join(sorted(used)) or 'no server successfully') + '.')
        say('  Choosing another server can share work; these counts alone do not prove why a download was faster.')
    else:
        say('  Static is simple: one server. Dynamic can spread requests across healthy servers.')
    if faster == 'STATIC':
        say('  STATIC was faster here. Possible reasons: srv1 had a good path and enough capacity,')
        say('  while dynamic needed new selection/rules or chose a different path. We did not isolate the cause.')
    elif faster == 'DYNAMIC':
        say('  DYNAMIC was faster here. Sharing work or choosing less busy paths may help;')
        say('  these timings alone do not prove which reason caused the difference.')
    if static['failures'] or dynamic['failures']:
        say('  For failed requests, the error lines explain the immediate problem. Do not hide them in averages.')
    say('  Tradeoff: static is simpler; dynamic needs monitoring and extra flow rules.')
    say('  One round per mode keeps the demo short. It does not prove which mode always wins.')
    say('-' * 66)
