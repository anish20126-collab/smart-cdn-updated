# Validation status

Executed in the restricted development environment:

- All project Python files parsed successfully.
- `bash -n demo.sh` passed.
- Mininet topology instantiated: six switches, ten hosts, nineteen links.
- Every configured inter-switch port, host port and host MAC matched the instantiated topology.
- OS-Ken test suite: **5 passed, 4 skipped** (9 total).
- Passed: selection/load policy; alternate paths; real OpenFlow parser serialization and bidirectional VIP rules; link reroute rule generation; VIP proxy ARP.
- Four live socket tests initially failed with `PermissionError: Operation not permitted` because this sandbox prohibits socket creation. They now explicitly skip under that restriction and remain executable on the VM.
- `sudo` cannot elevate here: the execution environment sets `no new privileges`.

Not executed here: live OS-Ken listener, TCP loopback tests, Mininet integration, actual congestion/failure experiments, or performance graph generation from live data. No integration or performance results have been fabricated.

To resolve: run `./sdn-env/bin/python -B -m unittest discover -s tests -v` and `./demo.sh` from a normal terminal on the Kali VM with working sudo. The demo writes actual results and exits nonzero on failed acceptance checks.

## Repository preparation (November 9, 2026)

The current unit suite was rerun: 5 passed, 4 socket tests skipped because this sandbox denies socket creation. An existing local live run, `results/20261108-092135`, was also found and inspected: all 11 saved acceptance checks are true, and its summary records 78 successes and zero failures. Selected unchanged measurements and graphs are preserved under `docs/sample-results/`. This saved evidence supersedes the earlier statement that no live results were available; it is not a newly executed integration run.
