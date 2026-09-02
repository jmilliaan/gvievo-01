# Modbus TCP digital I/O: scan engine + IO page

## Context

The vehicle has a 16-in / 16-out Modbus TCP I/O module at **192.168.1.30:502**
that nothing in this codebase talks to. It is the same hardware KIM2A uses, and
its drivers (`agv-kim2a-controller/drivers/modbus_di.py`, `modbus_do.py`) are the
working reference — but they are asyncio, coupled to a shared mutable `state`
object, and split the read and write halves across two files with no common
scan. This repo is threads + `snapshot()` + a strict profile, so the pattern is
worth porting rather than copying.

**Probed the real module read-only before planning.** It answers, and the
register map matches KIM2A's:

| fact | value |
|---|---|
| discrete inputs | address 0, 16 bits — currently `0010000000000000` (**DI2 ON**) |
| coils | address 0, 16 bits — all off |
| `device_id` | ignored; 1, 0 and 255 all answer |
| read latency | **2.0 ms**, 20/20 successful |
| pymodbus | 3.15.0 — same `device_id=` keyword API the KIM2A driver uses |

Two ms per read is the number that decides the architecture: two reads per scan
is ~4 ms, which is fine on its own thread and **not** acceptable on the 20 ms CAN
control tick, where it would be 20% of the budget and a network stall would be
far worse. So this mirrors `drivers/rfid.py`: own thread, own socket, publish an
immutable snapshot the control tick reads without blocking.

**Topology finding.** `ip route` confirms both devices sit on `enp2s0`, and the
RFID reader is reached *through* the DIO module's second port. The DIO module is
therefore a single point of failure for the RFID link, and
`RfidLink.carrier()` cannot see it — the PC's carrier is up because its link
partner is the DIO module, not the reader. A DIO health source makes that class
of fault diagnosable for the first time.

## Decisions taken

| Question | Decision |
|---|---|
| DI wiring | Something is connected but unmapped. Engine + page now; **no DI acts on the vehicle**. Names blank, filled in as the harness is buzzed out. |
| DO writes | **Display only.** No write path exists in the web app. DO lamps show coil state *read back* from the module, so a failed write would still read false. |
| Health tier | **Non-critical**, same as MLS and RFID: auto stops, manual is never held hostage to a device it does not use. |
| Concurrency | Threads + sync `ModbusTcpClient`, matching `RfidLink`. Do not drag asyncio in for one device. |
| Scan rate | 20 Hz (50 ms), matching KIM2A's DI loop. ~4 ms of work in a 50 ms period. |

## What "like a PLC" means here

The valuable property is not the loop itself but the **input image**: every
consumer sees one coherent set of bits sampled at one instant, rather than
reading a live socket at whatever moment it happens to ask. `snapshot()` under a
lock is exactly that, and it is the same discipline `_branch_scan()` already
follows for RFID.

The scan is: read DI → read DO coils → publish one immutable image. The write
phase of a real PLC scan is deliberately **absent**, not stubbed — with no write
path there is nothing to build it out of, and a dormant one would be a liability.
Its place is documented in the module docstring.

## Implementation

### 1. `drivers/dio.py` — the scan engine

Model on [drivers/rfid.py](drivers/rfid.py), which already solves the same
problem: a device on its own thread whose health the control loop pulls.

- `DioLink` with `start()`, `stop()`, `snapshot()`.
- Own thread, sync `ModbusTcpClient(config.DIO_IP, port, timeout)`. Reconnect on
  failure with a bounded retry period; never raise into the caller.
- One scan = `read_discrete_inputs(DI_BASE, count=NUM_DI)` then
  `read_coils(DO_BASE, count=NUM_DO)`. Apply `DI_FLIPPED` if set.
- `snapshot()` returns, under a lock: `di` and `do` bit lists, `connected`,
  `comms_ok`, `rx_age_s`, `scans`, `errors`, `detail`, plus `di_names`/`do_names`
  from the profile so the page needs no second fetch.
- `comms_ok` keys on **recent successful scans**, not on socket state. This is
  the opposite of `RfidLink._comms_ok()` and deliberately so: the reader is
  push-only and silence is normal, whereas we poll the DIO module every 50 ms, so
  silence *is* the fault. Comment the contrast at both sites.
- Gate on `config.DIO_ENABLED`; when false, report a `None` verdict so
  `health.py` reads it as "not in use" — the pattern
  [canworker.py:293](canworker.py#L293) already relies on for RFID.

### 2. `config.py` — a `dio` section

Add to `_SCHEMA` beside `rfid`, following the existing flat-key style:

```json
"dio": {
  "enabled": true, "ip": "192.168.1.30", "port": 502, "device_id": 1,
  "scan_period_s": 0.05, "timeout_s": 0.5, "reconnect_period_s": 2.0,
  "silent_warn_s": 1.0,
  "di_base": 0, "do_base": 0, "num_di": 16, "num_do": 16,
  "di_flipped": false,
  "di_names": ["","","","","","","","","","","","","","","",""],
  "do_names": ["","","","","","","","","","","","","","","",""]
}
```

`_SCHEMA` cannot express "a list of exactly `num_di` strings", so add
`_read_io_names(raw, count, where)` alongside `_read_ramp()`
([config.py:424](config.py#L424)) — the established escape hatch for structure
the flat table cannot hold. It must reject a name list whose length disagrees
with `num_di`/`num_do`, so a 16-lamp page can never be fed 12 labels.

Validate in `_validate()`: counts 1..256, bases >= 0, `scan_period_s` > 0 and
comfortably above `timeout_s`, `silent_warn_s` > `scan_period_s`.

### 3. `canworker.py` — own it, publish it

Beside the existing RFID wiring at [canworker.py:285-298](canworker.py#L285-L298):

- `self._dio = dio.DioLink()`, started and stopped with `self._rfid`.
- `self._hw.add(health.PullSource("dio", self._dio.snapshot), config.DIO_SILENT_WARN_S)`
  — registered unconditionally; the `None` verdict handles disabled.
- `snapshot()` gains a `"dio"` block.
- **No emits from the control tick.** Any DIO event belongs on an edge, and the
  50 Hz rule is enforced by the source scan in
  [tests/test_logging.py:72](tests/test_logging.py#L72). Connection
  gain/loss is edge-emitted from the DIO thread itself, like the branch events.

### 4. The IO page

New route `/io` in [app/server.py](app/server.py) beside `/monitor`, plus
`app/templates/io.html` and `app/static/io.js`, and a nav entry in
[app/templates/base.html](app/templates/base.html).

**In our idiom, not KIM2A's.** Its `io_monitor.html` is a standalone Win95-styled
page with 200 lines of inline CSS; ours extends `base.html` and uses the existing
dark tokens in [app/static/app.css](app/static/app.css) (`--warn`, `--bad`,
`--accent`, `--dim`).

- Two columns, 16 rows each: **Inputs** and **Outputs**.
- Each row: channel number, a lamp, and a name cell that is blank for now and
  wide enough to read once filled — a fixed-width column so adding names later
  does not reflow the page.
- Lamp: a `.lamp` / `.lamp.on` pair added to `app.css`. Off is a dim outline, on
  is filled `--accent` for DI and `--warn` for DO, so a glance distinguishes a
  live input from an energised output.
- A header strip showing link state, scan rate, scans and error count.
- **Stale must not look like off.** When `comms_ok` is false the whole grid dims
  and the header reads the fault — otherwise a dead module renders as 32 happily
  off lamps, which is the most dangerous thing this page could do.
- The page does **not** claim the auto watchdog (`window.CLAIM_HEARTBEAT` stays
  unset), so having it open cannot hold an auto run alive. That rule is already
  tested in `test_web.py` and the new page must not break it.

### 5. `drivers/modbus_io.py` — a read-only CLI

Same split as [read_mls.py](drivers/canbus/read_mls.py) / `tune_mls.py`: a
standalone script that prints DI/DO once or watches them, for commissioning
without the service running. Reads only — writes stay out of the repo until
there is a reason for them.

## Verification

1. **`python3 tests/run_all.py`** — raise `EXPECTED_CHECKS` deliberately.
   New `tests/test_dio.py`, against a fake client (no hardware):
   - a scan builds the input image; `DI_FLIPPED` inverts it
   - `snapshot()` returns a copy — a caller mutating it cannot corrupt the image
   - a read error marks `comms_ok` false and does **not** blank the last image
   - `comms_ok` goes false after `silent_warn_s` of failed scans
   - disabled reports a `None` verdict, so `health.py` never counts it
   - connection gain/loss emits once per edge, not per scan (count over 200
     scans, the same behavioural proof used for the branch events)
   - config: name list of the wrong length refused, bad counts refused,
     `silent_warn_s <= scan_period_s` refused
2. **`python3 -c "import config"`** still loads.
3. **Pages render:** `/io` 200, 32 lamps present, `/api/state` carries `dio`,
   and `/manual` `/auto` `/monitor` still 200.
4. **On the hardware** (service stopped, then restarted):
   - `python3 drivers/modbus_io.py` prints `DI2 ON`, matching the probe above.
   - Open `/io` — DI2 lit, all DO dark.
   - Toggle a physical input and watch the lamp follow within ~100 ms.
   - **Unplug the DIO ethernet:** the grid dims, health reports `dio` down, auto
     stops, manual still jogs. Replug and confirm it recovers on its own.
   - That unplug also drops RFID, which is the topology finding above — confirm
     both sources report, so the shared cause is visible rather than looking
     like two unrelated faults.

## Out of scope, and why

**Writing outputs** — no path from the web app, by decision. When one is added it
needs an arm-state interlock and event logging, not just a click handler.

**Acting on any input.** DI11 is E-stop and DI1/2/3 are lidar *in KIM2A's map*,
and this vehicle's DI2 is currently ON. The harness here is not yet mapped, so
this phase reads and displays only. **Nothing on this page makes the vehicle
safe** — once channels are identified, the E-stop and lidar hookup is its own
phase, and the health tier likely moves from non-critical to critical with it.

Analogue out (`modbus_ao.py`) — no AO module on this vehicle.
