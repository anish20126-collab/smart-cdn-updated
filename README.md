# Smart CDN — SDN and TCP Mini Project

Six clients download files from four servers through **one service address: `10.0.0.100:5000`**. An SDN controller chooses the server and tells the switches where to forward each connection.

This is a Mininet network emulation: it uses real TCP sockets, Linux network namespaces, Open vSwitch and OpenFlow 1.3. It is not a Python-only model.

## What stays simple

- One command runs the full demonstration: `./demo.sh`.
- One topology: six switches, six clients, four servers, nineteen links.
- One protocol: a JSON header followed by file bytes.
- One selection rule: choose the healthy reachable server with the lowest score.
- Three fault/load demonstrations: congestion, server failure and link failure.
- One comparison: fixed-server selection versus dynamic selection.

## Install on a dedicated Kali/Debian VM

After cloning your repository, open its `smart-cdn` directory:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mininet openvswitch-switch python3-matplotlib
python3 -m venv sdn-env
./sdn-env/bin/python -m pip install -r requirements-controller.txt
sudo systemctl start openvswitch-switch
```

Keep the existing working `sdn-env` if it is already installed. The controller uses its OS-Ken 4.2.2 environment; Mininet and plotting use system Python. The existing VM has Python 3.14.7; fresh installation on other versions has not been verified here.

## Run

```bash
./demo.sh
```

Run as your normal user; the script requests sudo only for Mininet. It starts the controller, creates the network, starts servers, verifies switch connections and ping connectivity, downloads files, exercises faults, runs comparison trials and plots results. Shutdown stops child processes and Mininet. Do not run multiple demos together.

For a shorter focused demonstration:

```bash
./demo.sh --scenario server-failure
./demo.sh --scenario comparison --trials 3
```

The full demo includes both. Other scenarios: `normal`, `congestion`, `link-failure`, `cli`. See [DEMO.md](DEMO.md) for the exact evaluation workflow.

## Topology

| Switch | Connected switches (Mbps) | Attached hosts |
| --- | --- | --- |
| s1 | s2 (50), s3 (30), s4 (30) | — |
| s2 | s1 (50), s5 (40), s6 (40) | — |
| s3 | s1 (30), s5 (20), s4 (10) | srv1, srv2 |
| s4 | s1 (30), s6 (20), s3 (10) | srv3, srv4 |
| s5 | s2 (40), s3 (20), s6 (10) | c1, c2, c3 |
| s6 | s2 (40), s4 (20), s5 (10) | c4, c5, c6 |

Server addresses are `10.0.0.11–14`; client addresses are `10.0.0.21–26`, all `/24`. Host links are 100 Mbps/2 ms. Switch links have 5 ms delay. The controller listens locally on port 6653. `network_config.py` holds shared links, addresses, MACs and switch ports.

## How a request works

1. A client opens a TCP connection to `10.0.0.100:5000`.
2. The controller answers ARP (address lookup) for the virtual IP.
3. The first TCP SYN reaches the controller, which chooses a healthy reachable server.
4. The controller installs connection-specific OpenFlow rules along computed paths.
5. At the client switch, the virtual destination is rewritten to the chosen server address. Reverse rules rewrite the response source to the virtual IP.
6. The server receives the request and streams file bytes. The client checks the length and SHA-256 checksum before keeping the file.

This is switch-based steering, not a Python proxy relaying downloads. Routes do not flood packets, so the redundant physical links do not create forwarding loops.

## TCP protocol

Each connection carries one request. Headers are UTF-8 JSON ending in a newline.

```text
Request:  {"op":"get","name":"document.pdf"}\n
Response: {"ok":true,"server":"srv1","size":2097152,"sha256":"..."}\n
          followed by exactly size bytes
Error:    {"ok":false,"error":"Content not found"}\n
Health:   {"op":"health"}\n  -> JSON status with active transfers and byte counters
```

The buffered reader handles fragmented TCP delivery. Headers are limited to 16 KiB. Servers handle clients concurrently using threads. The client handles timeouts, missing files, short transfers and checksum errors; partial files are removed. Filenames must exist in the server catalog, preventing directory traversal.

Sample `.pdf`, `.jpg`, `.mp3` and `.mp4` files are deterministic **synthetic binary data**, not valid media formats. All replicas serve identical content.

## Simple dynamic selection rule

For every new connection, ignore unhealthy or unreachable servers and choose the lowest score:

```text
utilization = max(forward Mbps, reverse Mbps) / capacity
link cost = 5 + 100 / max(0.1, capacity * (1 - min(0.99, utilization)))
score = shortest path cost + 20 * (active transfers + recent reservations)
        + 2 * server Mbps
```

Dijkstra's algorithm finds the lowest-cost path. A two-second reservation counts recently assigned connections until monitoring catches up. This prevents simultaneous arrivals from all seeing an idle replica. These are simple lab weights, not an optimal scheduling claim.

The controller reads switch byte counters approximately every second. A probe in c1 checks each server over the network and writes measured health/load to a shared file; data older than four seconds is rejected. Losing c1 or its probe stops new service selections until monitoring is restored.

## Fault behavior

- **Congestion:** twelve background video downloads target srv1; VIP requests run alongside them. Inspect measured counters and choices. Success alone does not prove congestion avoidance.
- **Server failure:** stop srv1, wait for health detection, verify new requests avoid it, then restart it. Existing connections to a dead server must reconnect.
- **Link failure:** disable a link from a recorded route. Port-state detection clears routes; subsequent packets cause path recalculation. Restore the link afterward. Transient loss and TCP retransmission are possible.

## Static versus dynamic methodology

The baseline fixes **server selection** to srv1 (`10.0.0.11`); dynamic requests use the VIP. Both still use the same controller-managed network. The baseline does not choose servers using load; ordinary controller-managed IP routing is retained. This compares server-selection policies, not SDN versus a non-SDN network.

Each of three paired trials runs six concurrent clients downloading the same 2 MiB `document.pdf` under each policy. Order alternates: static/dynamic, dynamic/static, static/dynamic. Each batch waits for four healthy idle servers and a four-second cooldown. No experimental background load is running during comparison; normal health probes remain active. The topology, bandwidth, file, clients and server processes are identical. Workload requests start as one batch of six processes, not precisely synchronized packet emission.

`comparison_method.json` records conditions. `requests.csv` records policy and trial. `comparison_trials.csv` reports each trial's successes, failures and successful-request averages. `comparison_summary.csv` averages those trial means and reports their sample standard deviation. Failed requests remain in the failure counts; an all-failed policy has blank averages, not fabricated zero performance. Throughput is bytes divided by completion time per request, not aggregate link throughput. Distribution counts successful requests, excluding health probes.

Graphs: `comparison.png` shows transfer time and throughput with trial standard deviations; `comparison_distribution.png` shows requests per server. Existing scenario, link and recovery graphs are also retained. Dynamic selection may be slower on some runs. Small samples, shared VM CPU, cached file data, persistent flow rules, policy order and residual monitoring noise limit conclusions. The comparison has no fault injection; failure recovery is evaluated separately for dynamic VIP traffic.

## Results and tests

```bash
./sdn-env/bin/python -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s tests -p test_topology.py -v
python3 plot_results.py results/<run>
```

Runs write `results/<timestamp>-<suffix>/`: requests, decisions, link/flow counters, recovery times, acceptance checks, comparison tables and graphs. False acceptance checks cause a nonzero demo exit status.

[Representative saved results](docs/sample-results/README.md) contain 78 successful requests, zero failures and eleven true acceptance checks from an earlier live run. **They do not contain the new comparison.** During this revision, seven unit tests passed; four socket tests skipped because the coding sandbox denies sockets, and the topology test skipped in the isolated controller environment. The topology test passed separately under system Python. New live integration and comparison have not run here: sudo is also blocked. Run the full demo in the VM terminal before claiming the updated end-to-end acceptance.

## Source guide

| File | Responsibility |
| --- | --- |
| `demo.sh` | One-command startup, results folder and controller cleanup |
| `experiment.py` | Named stages: connectivity, transfers, congestion, failures and comparison |
| `topology.py`, `network_config.py` | Network construction and shared constants |
| `sdn_launcher.py`, `simple_switch_13.py` | Start OS-Ken; handle ARP, rules, sessions and monitoring |
| `routing.py` | Shortest path and server score |
| `client.py`, `server.py`, `protocol.py` | TCP transfers, threaded serving and framing |
| `telemetry_agent.py` | Health and measured server traffic |
| `generate_content.py` | Repeatable sample content |
| `evaluation.py`, `plot_results.py` | Comparison statistics and graphs |
| `tests/` | Controller serialization, policy, transfer and statistics tests |
| `archive/` | Unused compatibility wrapper retained for reference |

Read [VIVA_EXPLANATION.md](VIVA_EXPLANATION.md) for function explanations and questions. The rubric audit is in [DEMO.md](DEMO.md).

## Troubleshooting and limits

- Missing module: install system Mininet/Matplotlib, or controller requirements in `sdn-env`, as appropriate.
- Switches do not connect: start OVS, check `controller.log`, and check port 6653 with `ss -ltnp`.
- Stale interfaces after a crash: run `sudo mn -c` only on the dedicated lab VM; it affects other Mininet experiments too.
- Failed acceptance: inspect `acceptance.json`, `requests.csv` and controller/server/health logs.
- Static IPv4 lab only: no discovery, TLS, IPv6, host mobility or migration of established server connections. Short idle/session timeouts suit brief lab transfers.

Virtual environments, generated downloads, logs and credentials are ignored by Git. Keep representative measured CSV/graphs in `docs/sample-results/` when adding a verified new run. No license has been selected by the author.
