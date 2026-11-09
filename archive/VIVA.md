# Teacher presentation and viva notes

## Opening explanation (30 seconds)

“My project delivers content using software defined networking. Six clients request files from one virtual IP, 10.0.0.100. Four servers hold identical copies. An OS-Ken controller checks server health and load, monitors OpenFlow traffic statistics, chooses a suitable server and path, and installs forwarding rules in six Open vSwitch switches. I demonstrate normal transfers, competing traffic, a stopped server and a broken network link.”

Run `./demo.sh` from the normal Kali VM terminal. The terminal now explains each phase, draws the topology, prints verified transfers and controller-selected routes, and ends with readable acceptance checks.

## Explain each phase as it runs

| Phase | What to say | What counts as evidence |
|---|---|---|
| Controller connections | “All six switches connect to the controller using OpenFlow 1.3.” | Six switches in the controller snapshot |
| Connectivity | “Proxy ARP and controller-computed IPv4 paths provide connectivity without broadcast flooding.” | Zero packet loss in pingAll |
| Content delivery | “Clients request the VIP. The controller selects the real server, and the received binary file is checked using SHA-256.” | PASS, byte count, selected replica, time and throughput |
| Load distribution | “Concurrent connections can go to different replicas, using measured load and path costs.” | Different server names and recorded decision scores |
| Congestion | “Twelve real downloads compete with service requests over bandwidth-limited links.” | Server load, port measurements, selected paths and performance CSVs |
| Server fault | “I deliberately stop srv1. The health probe detects this and the controller avoids it for new connections.” | UNAVAILABLE for srv1, successful new requests to other servers |
| Link fault | “I disable a link from a recorded route. Port-state detection invalidates old forwarding, and new requests use available paths.” | Named disabled link and new recorded routes without it |
| Restoration | “The failed components are restored and clients make final verified requests.” | Final PASS/FAIL checklist |

A stopped component is an **intentional experimental fault**. The test passes when the specified service recovers. A timeout, checksum mismatch or failed acceptance check is a real failure; explain it rather than hiding it.

## Read the route output

Illustrative format only; your run prints its own recorded decisions:

```text
[PASS] c1 received document.pdf from srv1 | SHA-256 verified | ...
       Controller-selected request route: c1 -> s5 -> s3 -> srv1
       Decision: score=... (lower is better), active transfers=..., server traffic=... Mbps
```

The server name comes from the actual response. The route comes from the controller's decision CSV, matched using the client's TCP source port. It is a **controller-selected route**, not a packet capture proving every packet traversed it. Route recomputation can occur after selection. Return traffic has reverse forwarding and translation so the client continues seeing the VIP.

Show a failed link by referring to the specific name printed by the demo, not an assumed link. Compare the prior route with subsequent selections. A new request might use an alternate path to the same replica or select a different healthy replica.

## Likely questions and short answers

**What is SDN?**
The control plane decides forwarding centrally; the switches execute rules in their data plane. OS-Ken is the controller and OVS implements OpenFlow rules.

**Why use a virtual IP?**
Clients need one stable address. They do not choose a physical server or need to know which replica is healthy.

**Is this just Python choosing a server address?**
No. The client connects to the VIP. OS-Ken installs TCP-specific OpenFlow rules that translate addresses and steer the actual traffic along computed switch paths.

**How does ARP work for an address no physical server owns?**
The controller replies to ARP requests for the VIP with a virtual MAC address. It also answers for known hosts; ARP is not flooded through the mesh.

**How do you select the server?**
Exclude unhealthy or unreachable servers. Compute a path cost using link capacities and measured utilization in both directions. Add penalties for active transfers, recent new assignments and measured server throughput. Choose the lowest score.

**Why does the smallest score win?**
It represents a cheaper path and less observed server pressure under our lab heuristic. It is not a claim of mathematically optimal end-to-end latency.

**Where do the measurements come from?**
OpenFlow port byte counters produce Mbps from counter differences divided by elapsed time. Servers report active transfers and cumulative bytes over TCP health requests. Flow statistics provide packet and byte counters.

**Why do you check traffic in both link directions?**
Content requests are small, but downloads are large. Reverse-path congestion matters to a download even if the request direction is quiet.

**How is the load balancing dynamic?**
Each new TCP connection is selected using current telemetry. Existing connections keep their replica to avoid breaking TCP. Distribution need not be exactly equal.

**What keeps the redundant topology from creating loops?**
The controller does not flood unknown traffic. It answers ARP and installs unicast paths computed by Dijkstra. On port changes it invalidates application routes and recomputes paths. Updates are asynchronous and may cause transient packet loss.

**What happens if a server fails mid-download?**
That connection fails or times out and must reconnect. New connections can use other healthy replicas. TCP state is not migrated between servers.

**What happens if a link fails?**
OpenFlow port-state messages reveal the fault. The controller removes old routes and computes available paths. TCP retransmissions may recover some existing connections; the automated test verifies new requests.

**What does recovery time mean?**
Elapsed time from the fault command to completion of a successful new verified transfer. It includes health/port detection, retries, rule setup and file transfer, not only controller processing.

**What does PASS prove?**
Only the named condition. For example, transfers completing under competing traffic does not alone prove the selection algorithm improved congestion performance. Use port data, decision logs and repeated comparisons to discuss that.

**Are these real videos and PDFs?**
They are generated binary transfer fixtures with illustrative extensions, not playable media. The project demonstrates correct TCP binary delivery and SHA-256 verification without external downloads.

**Why Mininet rather than real switches?**
Mininet uses Linux network namespaces and virtual Ethernet links to emulate hosts and switches on one machine. OVS applies real OpenFlow rules; TCLink limits bandwidth and adds delay.

**What are the main limitations?**
Fixed known topology, IPv4 only, simple heuristic weights, shared-filesystem telemetry from c1, no TCP state migration, and no security layer. The project is a basic SDN demonstration rather than a production CDN.

## Finish with evidence

Open the result directory printed by the demo:

- `acceptance.json`: machine-readable pass/fail results.
- `decisions.csv`: server selection and switch paths.
- `requests.csv`: individual client results and TCP source ports.
- `ports.csv`: actual link traffic and utilization.
- `recovery.csv`: observed server/link recovery time.
- `graphs/`: performance, server distribution, client times, links and recovery.

Conclude with what your actual run shows. Do not claim zero downtime, equal balancing, or optimal routing unless the measurements support it.
