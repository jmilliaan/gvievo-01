# Deviation D1: `/manual` was opened three times during the session

The session rule is that nobody opens `/manual` on any device, because the
arrow keys on that page jog the wheels.

| Time | Process | Vehicle state at that moment |
|---|---|---|
| 15:32:20 | 16679 | `armed=true, mode=manual`, target 0/0, rpm 0/0 |
| 15:32:33 | 16679 | `armed=true, mode=manual`, target 0/0, rpm 0/0 |
| 15:34:14 | 17922 | `armed=false, mode=idle`, dry_run true, target 0/0, rpm 0/0 |

## No motion resulted

- The service request log for the whole session contains **no POST or PUT
  requests of any kind**, so `/api/drive` was never called. The page was
  loaded, never used to command.
- The 5 Hz setpoint poll covers all three loads. `target` stayed 0/0 and both
  `nodes[*].rpm` stayed 0 continuously. `statepoll-ALARMS.txt` is empty for the
  entire session.
- At the third load the vehicle was disarmed, so a jog could not have been
  actioned even if a key had been pressed.

The browser was moved to `/auto` when this was raised. Recorded as a protocol
deviation with no physical consequence; no case result depends on it.

Also recorded from the same log: the selector was moved MANUAL -> AUTO at
15:32:29 (`armed/manual` -> `idle` in the poll).
