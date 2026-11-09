# Explain the project simply

## A short introduction

“My project delivers files to six clients from four replica servers. Clients know only one virtual address. The SDN controller chooses a healthy server and programs the switches. I use TCP sockets to send actual file data and SHA-256 to check it arrived correctly. I demonstrate normal delivery, load, server failure, link failure, and compare fixed-server selection with dynamic selection.”

SDN means software-defined networking: control decisions happen in the controller, while switches forward packets using its rules. Mininet creates virtual hosts and links on one Linux VM. Open vSwitch implements the switches. OS-Ken is the Python framework that speaks OpenFlow to those switches. OpenFlow 1.3 is the protocol for installing forwarding rules and reading counters.

TCP sockets provide a reliable ordered byte stream. TCP does not preserve message boundaries, so our newline header and declared file length explain where messages end. SHA-256 is a digest of file bytes; the receiver calculates it independently and compares it with the server's value.

## Network and roles

There are six switches and nineteen links: nine between switches and ten to hosts. All switch connections are listed below; the same link appears from both endpoints.

| Switch | Neighbors | Hosts |
| --- | --- | --- |
| s1 | s2, s3, s4 | none |
| s2 | s1, s5, s6 | none |
| s3 | s1, s4, s5 | srv1 (.11), srv2 (.12) |
| s4 | s1, s3, s6 | srv3 (.13), srv4 (.14) |
| s5 | s2, s3, s6 | c1 (.21), c2 (.22), c3 (.23) |
| s6 | s2, s4, s5 | c4 (.24), c5 (.25), c6 (.26) |

All IPs begin `10.0.0`. Servers hold identical files. Clients request files. The virtual IP `.100` belongs to the service, not to a physical host. The controller answers address-resolution requests for it and rewrites service packets.

## Follow one download

1. c1 connects to `.100:5000` and the first connection packet reaches OS-Ken.
2. OS-Ken checks health, active transfers and network measurements, then selects a replica.
3. It installs rules matching client/server IPs and TCP ports along a computed path.
4. The client-edge switch changes the virtual destination to the chosen replica. Intermediate rules match the physical address.
5. The server accepts the socket, reads the JSON header and sends a size/checksum header followed by bytes.
6. Return rules send traffic toward the client; its edge changes the source to `.100` so the TCP connection sees the expected peer.
7. The client reads exactly the declared size, checks SHA-256 and renames its temporary file only after success.

A flow rule contains a match (which packets it applies to), actions (rewrite/output), priority and timeout. A table-miss rule sends unmatched packets to the controller. Computed paths and proxy ARP avoid broadcast flooding and loops.

## Selection, load and faults

The controller excludes unhealthy/unreachable servers, computes a path cost, and picks the lowest total score. The score adds path cost, 20 times active/recently assigned transfers, and twice measured server Mbps. A link becomes more costly as available bandwidth falls. Dijkstra finds the least costly path. The exact formula and units are in README.md.

Recent reservations last two seconds because several requests may arrive before the next load sample. The selected server remains fixed for that TCP connection. New connections can receive different servers.

Switch port-byte changes divided by sample duration give Mbps. Comparing rate with link capacity gives utilization. c1 probes servers over actual TCP and reads active-transfer and cumulative-byte counters; the controller rejects stale telemetry after four seconds. This is a deliberately simple shared-file monitoring channel.

During congestion, real background transfers compete for bandwidth. We inspect measured utilization and selection decisions; successful downloads alone do not prove that the best path was selected.

During server failure, health checks mark srv1 unavailable, new connections select other replicas, and srv1 is restarted. An existing connection to a dead server must reconnect. During link failure, OpenFlow port status marks the link down and clears application rules. Paths are recomputed without that link. Transient loss/retransmission can occur; we test successful new connections rather than promise seamless migration.

## Understand the measurements

Transfer time includes connection, request, data transfer and verification. Per-request throughput is received bytes times eight divided by elapsed seconds and one million. Success means complete, checksum-verified transfer. Distribution counts successful file requests per server. Recovery time runs from issuing a fault to a successful new verified transfer; it includes detection and transfer time.

The static baseline always requests srv1 directly; it still uses controller-managed routing. The dynamic policy requests the virtual service. Each uses the same six clients, 2 MiB file and unchanged network, with three paired trials and alternating order. No fault or background load is injected in the comparison. Failures are reported separately from successful timing averages. Standard deviation describes variability between trial means.

Timing graphs compare observed completion times. Throughput graphs compare successful per-request rates. Distribution graphs show whether requests spread across servers. They do not prove optimal routing, universal superiority, aggregate network capacity or uninterrupted established connections. VM scheduling, caches and a small sample affect results. The old saved run is real evidence, but it has no static comparison; the new comparison must be run before reporting a conclusion.

## Important files and functions

| File / function | Plain explanation |
| --- | --- |
| `demo.sh` | Requests sudo, generates files, starts OS-Ken, runs the experiment, plots and stops its controller |
| `topology.SmartCDN.build` | Creates switches, hosts and the shared link list |
| `network_config.py` | Stores addresses, MACs, capacities and exact port numbers |
| `sdn_launcher.main` | Configures OS-Ken on localhost:6653 and loads the controller |
| `routing.shortest_path` | Finds a path avoiding unavailable or expensive links |
| `routing.select_server` | Scores healthy reachable replicas and returns the best |
| `SimpleSwitch13.features`, `state` | Register connected switches and handle disconnection |
| `update_port`, `descriptions`, `port_status`, `down_links`, `invalidate` | Track availability and clear routes after network changes |
| `monitor`, `port_stats`, `flow_stats`, `record` | Read telemetry, request counters and save measurements |
| `add_flow`, `emit`, `proxy_arp` | Send a rule, output a packet, answer address lookup |
| `path_rules`, `service_rules` | Install path forwarding and bidirectional virtual-IP rewrites |
| `packet_in` | Read unmatched traffic, select or reuse a connection's server, install rules |
| `protocol.send_header`, `read_header` | Send/read one bounded newline JSON header |
| `ContentServer.__init__` | Build the file catalog/checksums and create a threaded listening socket |
| `Handler.handle` | Receive a request, return health/error or stream the requested file; maintain counters under a lock |
| `server.main` | Parse options, start accepting connections with `serve_forever` |
| `client.fetch` | Connect, request, receive, verify, keep the file or return an error |
| `client.main` | Turn command-line arguments into one fetch and print JSON |
| `telemetry_agent.probe`, `main` | Probe four servers concurrently and publish health/rates |
| `generate_content.generate` | Create repeatable synthetic files and a checksum manifest |
| `Demo.start`, `spawn`, `start_server`, `wait_for`, `controller`, `health` | Start processes and wait for actual readiness/connectivity |
| `Demo.batch`, `background`, `recovery_probe` | Run concurrent requests, add real load, test recovery |
| `normal_delivery`, `congestion`, `server_failure`, `link_failure`, `compare`, `run` | Clearly named demonstration stages |
| `Demo.save`, `stop_processes`, `close` | Write measurements and clean up network/processes |
| `presentation.py` | Print stages, measured routes, health and acceptance results |
| `evaluation.summarize` | Group actual comparison records into trial statistics and distribution |
| `plot_results.read`, `plot` | Read actual CSV and create summaries/graphs |
| `tests/` | Check routing, real OpenFlow serialization, transfers and statistics |

The optional server `--rate` setting paces each transfer in bytes/sec; the normal demo leaves it disabled. The core server class uses Python's standard threaded TCP server so each accepted client runs independently. Shared counters use a lock to prevent concurrent updates from interfering.

## 25 likely questions

1. **What problem do you solve?** Clients receive content without choosing or tracking physical replicas.
2. **Why SDN?** A central program chooses servers/paths and changes forwarding when conditions change.
3. **Why TCP?** Reliable ordered byte delivery suits file downloads.
4. **Is this only a mathematical simulation?** No. Mininet emulates a network carrying real sockets and OpenFlow traffic.
5. **What is Mininet?** A tool creating isolated virtual hosts, switches and links on Linux.
6. **What is Open vSwitch?** Software implementing the packet-forwarding switches.
7. **What is OS-Ken?** The controller framework handling OpenFlow events and messages.
8. **What is OpenFlow?** The protocol the controller uses to program switch rules and read statistics.
9. **How many nodes?** Six switches, six client hosts and four server hosts.
10. **What is the VIP?** `10.0.0.100`, the logical service address used by dynamic clients.
11. **Does the controller relay file bytes?** No. It programs switches; packets then follow installed rules, though initial unmatched packets reach it.
12. **How is a server selected?** Lowest score among healthy reachable replicas, considering path cost and measured load.
13. **Why temporary reservations?** They count new assignments before monitoring reflects them.
14. **How are loops avoided?** Computed forwarding paths and proxy ARP; no broadcast flooding.
15. **How are replies recognized by the client?** Reverse rules rewrite the server source to the VIP.
16. **How is TCP framed?** One newline JSON header, then exactly the declared number of bytes.
17. **How do you handle six clients?** Separate concurrent client processes and threaded server handlers.
18. **How do you verify a file?** Check declared length and SHA-256 before retaining it.
19. **What if the file is missing?** Send an error header; client reports failure.
20. **How is congestion measured?** Port-byte counter changes over time, divided by link capacity for utilization.
21. **What if a server fails?** Probes mark it unhealthy; new VIP connections use other servers. Existing failed connections must reconnect.
22. **What if a link fails?** Port-state detection clears old rules and new paths avoid that link.
23. **What is the baseline?** Fixed srv1 selection over the same controller-managed topology.
24. **What do error bars mean?** Sample standard deviation of the measured per-trial means, not a guarantee or confidence interval.
25. **Must dynamic always perform better?** No. Report actual measurements, failures, variation and limitations honestly.
