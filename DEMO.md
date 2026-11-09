# Evaluation demo

Run these from `~/smart-cdn` in your normal Kali VM terminal. Setup is in README.md. Keep the working Python environment.

```bash
cd ~/smart-cdn
sudo systemctl start openvswitch-switch
./sdn-env/bin/python -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s tests -p test_topology.py -v
python3 -B -m unittest discover -s tests -p test_pairing.py -v
./demo.sh
```

The final command manages the controller and network; no extra terminal is required. Enter your sudo password when asked. Do not run the whole script with sudo: the controller should remain unprivileged. Allow several minutes for real downloads, faults and one static and one dynamic batch per case.

## What to explain as it runs

1. All six switches connect using OpenFlow 1.3; all-host ping must show zero loss.
2. Six clients request the VIP; each successful download prints the actual server and verified checksum.
3. More than one selected server demonstrates distribution. Detailed controller paths remain in `decisions.csv`; the screen shows simple client/server changes.
4. Background TCP traffic creates load. The controller reads measured counters rather than invented load values.
5. srv1 stops; new requests use the remaining servers. The script restarts srv1.
6. A used switch link goes down; the controller detects it and recalculates routes. The script restores it.
7. Every mixed-file/load/fault test compares static and dynamic with identical clients/files, static then dynamic in the default single round. Read its RESULT and WHAT WE LEARNED before moving on.
8. The final acceptance checklist and printed results folder provide evidence. Outages print `[FAULT] ... FAILED / OFFLINE` or `FAILED / DOWN`. `[PASS]` means a transfer or recovery check succeeded; `[FAIL]` means a transfer/check actually failed. Any FAIL requires investigation.

Inspect the printed folder:

```bash
cat results/<run>/acceptance.json
cat results/<run>/comparison_summary.csv
cat results/<run>/comparison_distribution.csv
ls results/<run>/graphs/
```

Top-level comparison graphs are `comparison.png` and `comparison_distribution.png` for normal traffic. Every condition has its own CSV/graphs under `comparison_cases/<condition>/`. Explain successful request counts alongside timing; averages exclude failures. Error bars are available only when you request repeated trials; one round cannot measure between-round variability. Never assume dynamic must win.

## Shorter commands

```bash
./demo.sh --scenario server-failure
./demo.sh --scenario link-failure
./demo.sh --scenario comparison --trials 1
./demo.sh --scenario cli
```

Focused fault demos retain normal delivery checks. Comparison-only runs connectivity then comparison, avoiding the longer congestion/media scenarios. CLI starts the network and servers until `exit`:

```text
pingall
c1 python3 client.py 10.0.0.100 document.pdf
sh ovs-ofctl -O OpenFlow13 dump-flows s5
exit
```

Ctrl-C requests shutdown. Fault methods restore servers/links in `finally` blocks; process cleanup terminates clients/servers/probes and stops Mininet. After an abnormal crash, `sudo mn -c` cleans stale Mininet resources on this dedicated VM.

## Rubric audit (40 marks)

This maps the supplied rubric to implementation and evidence; it does not predict marks. Old saved evidence predates this revision. New comparison/integration evidence remains pending a VM run.

| Criterion | Files | Demonstration and evidence |
| --- | --- | --- |
| D1 Problem Understanding & Architecture — 2 | README, topology, network_config | Topology table; topology consistency test |
| D1 TCP/UDP Socket Implementation — 4 | client, server, protocol | Concurrent binary downloads, checksums; TransferTests (skipped in sandbox; run on VM) |
| D1 Mininet + SDN Implementation — 4 | topology, controller, routing | Six switch connections, pingAll, OpenFlow dumps; ControllerTests; saved connectivity.json |
| D1 Socket–SDN Integration — 3 | controller service_rules/packet_in, client | VIP request, server choice and rewrite rules; serialization test; saved decisions/requests |
| D1 Initial Testing & Demo — 2 | tests, demo.sh | Unit suite and full demo; acceptance.json |
| D2 Complete Application Functionality — 4 | client, server, experiment | Six clients, content types, checksum failures; saved requests and VM transfer tests |
| D2 Dynamic SDN Functionality — 6 | routing, controller, telemetry_agent | Load-aware choices and alternate paths; policy/controller tests, decisions/ports.csv |
| D2 Challenging Scenario / Robustness — 4 | experiment fault methods | Stop server, disable used link, congestion; saved recovery/acceptance; rerun on VM |
| D2 Performance Evaluation & Comparison — 5 | experiment.compare, evaluation, plot_results | Two paired trials, timing/throughput/distribution/stddev; statistics tests pass; new live CSV/graphs pending |
| D2 Documentation, Final Demo & Viva — 6 | README, DEMO, VIVA_EXPLANATION | One-command workflow, source explanation, 25 questions; final VM rehearsal pending |

## Revision validation

Before editing: 5 tests passed; 4 socket tests skipped. After editing: statistics tests added; see the final report for the current count. Python parsing and shell syntax/help checks run locally. No live network test was rerun here because the execution sandbox denies sockets and sudo. Prior unchanged evidence is in `docs/sample-results/`. Fresh environment installation and the new full live demo are not yet verified.

## Present slowly to an audience

```bash
./demo.sh --present
```

Press Enter between sections when ready. Without `--present`, the same demo runs automatically. The terminal explains the topology, labels STATIC/DYNAMIC, prints one line per download, and announces a changed server for a new request. It does not imply an established connection moved. FAULT means a server/road is down; RESTORED means it is available again. FAIL means a download/check did not work. Technical counters and routing details remain in CSV/logs. The final screen summarizes checks; `acceptance.json` contains every individual result. Do not include manual presentation pauses in performance conclusions about overall demo runtime; transfer timings start inside each client.

The mixed-file normal test and each load/fault condition now compares both modes across one paired round. The restored-network check also compares both modes. Use `--trials N` to change the paired round count. More tests mean the full demo takes longer; comparison-only remains the shortest paired demonstration. Each condition prints delivery counts, successful timing, server distribution and a short explanation. Large red banners (on an interactive terminal) announce actual confirmed outages. Static downloads failing during the server-offline test are expected: keep that failure visible and explain why dynamic can choose a replacement. One round is a demonstration, not a strong benchmark.

## Current fast defaults

The full presentation is five cases: mixed-file normal delivery, congestion, server failure, link failure, and restoration. Each case runs STATIC once and DYNAMIC once (six clients each). File types are combined in the first case, not tested in separate stages. Other cases use document.pdf to keep comparisons short and identical. No variability estimate is available from one round. Target runtime is under five minutes, excluding unusually long explanations or VM delays; actual elapsed time is printed. The revised runtime remains unverified until a VM run.
