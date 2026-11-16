"""Operator panel and horn over the DIO island (T12), framework-free.

Reuses the repo's own pieces unchanged: core/panel.PanelScan for the
debounced Reset/Start edges and the AUTO/MANUAL level (anti-tie-down at
power-on, re-baseline after a comms gap - see its docstring), and
drivers/dio.DioLink for the Modbus scan thread and the expiring coil claim.

    PanelAdapter.tick(snapshot)       -> PanelFrame  (what to publish)
    PublishGate.due(now, frame)       -> bool        (publish it now: once per acquisition + fallback)
    alarm_wanted / call_wanted / motion_outputs      (what the dio coils should be)
    coil_image(normal, ...)                          (all of them; every one LOW while not NORMAL)

The jog pendant rides in the same frame: core/panel.DebouncedLevels over the
four PENDANT_DI_* channels, resolved by core/panel.pendant_intent (an opposing
pair cancels). Levels, reported as-is; the mux turns them into a twist.

Policy that lives here, and nowhere else on the ROS side:

  * The panel image is VALID only while DIO comms are good AND PanelScan has a
    debounced baseline. Anything else publishes valid=false, which the mux and
    the executor treat as no authority at all (gating.Panel).
  * Every coil (dio.motion_on / alarm_on) is a claim renewed every tick with
    config.HORN_HOLD_S, so a dead node drops it on the next DIO scan. Nothing gates
    on them; a horn that failed cannot stop a move (README, safety model). The
    legacy setpoint-following horn.* engine is retired (lean plan D16, 2026-11-16).
  * E-stop signal (panel.di_estop, DI09 = Flexi Soft Q3, emergency-suite plan Part B). Owner
    2026-11-16: active = HIGH (panel.estop_active_high), LOW / no signal = normal; informational,
    not safety. Filtered both ways (active over estop_confirm_scans, clear over debounce_scans)
    on valid images only. An invalid or stale image HOLDS the last belief: a DIO gap is never an
    E-stop. panel_node feeds it to amr_base.emergency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from agv_core import config
from agv_core import panel as panel_core  # repo module: core/panel.py

from amr_base import emergency
from amr_base.hold_policy import CALL_CAUSES


@dataclass(frozen=True)
class PanelFrame:
    valid: bool
    mode_auto: bool
    start_edge: bool
    reset_edge: bool
    seq: int
    comms_ok: bool
    changed: str | None = None  # human-readable transition for the log, if any
    pendant: panel_core.PendantIntent = panel_core.PENDANT_IDLE
    manual_arm: bool = False  # panel.di_manual_arm, debounced; False while invalid
    # Debounced levels of Start and Reset (2026-11-11, the At home combination). False while invalid.
    start_held: bool = False
    reset_held: bool = False
    # A new DIO acquisition was evaluated (not a republish of the last one): publish it (WP-C3).
    acquired: bool = False
    # The DIO link edge as a catalogue code (WP-H2): DIO_LINK_LOST / DIO_LINK_OK, None = no edge.
    link: str | None = None
    link_text: str | None = None
    # `changed` without the link note: the PANEL event's text, and whether it is a warning.
    other: str | None = None
    warn: bool = False
    # The E-stop signal NOT active (panel.di_estop, DI09; kyb contract name): active over
    # estop_confirm_scans, clear over debounce_scans; held as it was while the image is invalid.
    estop_ok: bool = True


LINK_LOST, LINK_OK = "DIO_LINK_LOST", "DIO_LINK_OK"
# PANEL notes that are a warning, not news (an invalid image, a suspect edge).
_WARN_NOTES = ("invalid", "suspect")


def raw_hex(di) -> str:
    """The DI image as one word, DI00 = bit 0: the evidence for a phantom image's source."""
    try:
        return f"0x{sum(1 << i for i, b in enumerate(di) if b):04X}"
    except TypeError:
        return "?"


class PanelAdapter:
    """Turns DioLink snapshots into PanelFrames. One instance per node."""

    def __init__(
        self,
        debounce_scans: int | None = None,
        pendant: bool | None = None,
        coincidence_hold_scans: int | None = None,
        estop_confirm_scans: int | None = None,
        estop_active_high: bool | None = None,
    ) -> None:
        scans = config.PANEL_DEBOUNCE_SCANS if debounce_scans is None else debounce_scans
        if estop_confirm_scans is None:
            estop_confirm_scans = config.PANEL_ESTOP_CONFIRM_SCANS
        if estop_active_high is None:
            estop_active_high = config.PANEL_ESTOP_ACTIVE_HIGH
        # Coincidence guard: the selector and the pendant changing in the SAME debounced scan
        # is not a hand (2026-09-17: MANUAL+FWD appeared together for 1.02 s mid-route with
        # nobody at the box, aborting the run and handing the mux a phantom FWD). Both changes
        # are withheld - the previous selector and an idle pendant are published - until the
        # new image has persisted this many scans; if it reverts first, nothing happened.
        if coincidence_hold_scans is None:
            hold_s, period = config.PANEL_COINCIDENCE_HOLD_S, config.DIO_SCAN_PERIOD_S
            coincidence_hold_scans = int(math.ceil(hold_s / period))
        self.hold_scans = max(0, coincidence_hold_scans)
        # Edge guard (2026-10-24: a phantom START with Manual Arm off in the same scan, selector
        # already AUTO, started a line run with nobody at the box). A Start or Reset edge believed
        # in the same scan as - or the scan after - any other input change is not a hand: it is
        # dropped, never delayed, and the operator presses again. Only ever removes authority.
        self._other_changed_scan: int | None = None  # acquisition of the last non-button change
        self._acq = 0
        self._held: tuple[str, panel_core.PendantIntent] | None = None  # (mode, pendant) being withheld
        self._held_for = 0
        self.scan = panel_core.PanelScan(
            config.PANEL_DI_RESET,
            config.PANEL_DI_START,
            config.PANEL_DI_AUTO,
            scans,
            auto_when_on=config.PANEL_AUTO_WHEN_ON,
        )
        self.pendant = None
        if config.PENDANT_ENABLED if pendant is None else pendant:
            self.pendant = panel_core.DebouncedLevels(
                (
                    config.PENDANT_DI_FWD,
                    config.PENDANT_DI_RVS,
                    config.PENDANT_DI_LEFT,
                    config.PENDANT_DI_RIGHT,
                ),
                scans,
            )
        # Manual Arm (DI08): a debounced LEVEL, like the pendant. A switch already on at
        # power-on powers the drives once the image is valid - power is not motion.
        self.manual_arm = panel_core.DebouncedLevels((config.PANEL_DI_MANUAL_ARM,), scans)
        self._last_arm: bool | None = None
        # E-stop signal (DI09, Flexi Soft Q3): active needs estop_confirm_scans (kyb 2026-11-02:
        # one-scan Q3 test pulses), clear needs debounce_scans. Counted on valid images only; an
        # invalid image or a comms gap holds the belief (owner 2026-11-16: not an E-stop).
        self.estop_scans = scans
        self.estop_confirm_scans = max(1, int(estop_confirm_scans))
        self.estop_active_high = bool(estop_active_high)
        self._estop_on = 0
        self._estop_off = 0
        self._estop_active = False
        self._last_estop: bool | None = None
        self.seq = 0
        self._last_scans: int | None = None  # DIO acquisition count behind the last evaluated frame
        self._last_frame: PanelFrame | None = None
        self._last_valid: bool | None = None
        self._last_mode: str | None = None
        self._last_comms: bool | None = None
        self._last_pendant: panel_core.PendantIntent | None = None
        # Pendant release-before-use (owner decision 2026-10-25, unified plan WP-A6): a direction
        # held when the pendant becomes able to drive - the image (re)baselined, the published
        # selector turning MANUAL, Manual Arm switching on - publishes idle until it has been
        # read LOW once. There is no enabling device and the FX3 does not see the pendant.
        self._must_release: set[str] = set()

    @staticmethod
    def source_fresh(snapshot: dict) -> bool:
        """Is the DIO image CURRENT physical input? Connected, and a successful scan within
        PANEL_SOURCE_MAX_AGE_S - not the 2 s diagnostic silence age (audit R01)."""
        age = snapshot.get("rx_age_s")
        return (
            bool(snapshot.get("comms_ok"))
            and bool(snapshot.get("connected", True))
            and age is not None
            and age <= config.PANEL_SOURCE_MAX_AGE_S
        )

    def tick(self, snapshot: dict, normal: bool = True) -> PanelFrame:
        """`normal`: the emergency state (amr_base.emergency) is NORMAL. While it is not, every
        pendant direction held is masked until read LOW once (WP-A6's release-first rule): a hand
        held through the E-stop and the Reset does not drive when NORMAL returns."""
        comms = self.source_fresh(snapshot)
        scans = snapshot.get("scans")
        self.seq += 1
        # The node ticks at 50 Hz, the DIO scans at 20 Hz. Debounce, edges and the
        # coincidence hold count ACQUISITIONS: a tick on an image already evaluated
        # republishes the last frame, edges spent.
        if comms and self._last_frame is not None and scans is not None and scans == self._last_scans:
            return PanelFrame(
                valid=self._last_frame.valid,
                mode_auto=self._last_frame.mode_auto,
                start_edge=False,
                reset_edge=False,
                seq=self.seq,
                comms_ok=True,
                pendant=self._last_frame.pendant,
                manual_arm=self._last_frame.manual_arm,
                start_held=self._last_frame.start_held,
                reset_held=self._last_frame.reset_held,
                estop_ok=self._last_frame.estop_ok,
            )
        self._last_scans = scans
        self._acq += 1
        last_pend = self._last_pendant if self.pendant is not None else panel_core.PENDANT_IDLE
        prior = (self._last_mode, last_pend, self._last_arm)
        intent = self.scan.scan(snapshot.get("di"), comms)
        notes = []
        link = link_text = None
        if comms != self._last_comms:
            link = LINK_OK if comms else LINK_LOST
            link_text = "DIO comms " + ("ok" if comms else f"LOST ({snapshot.get('detail')})")
            notes.append(link_text)
            self._last_comms = comms
        prior_valid = self._last_valid
        if intent.valid != self._last_valid:
            notes.append("panel image " + ("valid" if intent.valid else "invalid"))
            self._last_valid = intent.valid
        # (the selector note is written by _coincidence, once the change is believed)
        pend = panel_core.PENDANT_IDLE
        levels = None
        if self.pendant is not None:
            levels = self.pendant.scan(snapshot.get("di"), comms)
            if levels is not None:
                pend = panel_core.pendant_intent(*levels)
        was_valid = prior_valid
        arm_levels = self.manual_arm.scan(snapshot.get("di"), comms)
        arm = bool(intent.valid and arm_levels is not None and arm_levels[0])
        start, reset = bool(intent.start), bool(intent.reset)
        if intent.valid and None not in prior:
            others = [n for n, was, now in zip(("selector", "pendant", "Manual Arm"), prior,
                                                (intent.mode, pend, arm), strict=True) if was != now]
            if others:
                self._other_changed_scan = self._acq
            recent = self._other_changed_scan is not None and self._acq - self._other_changed_scan <= 1
            if (start or reset) and recent:
                edges = "+".join(n for n, on in (("START", start), ("RESET", reset)) if on)
                notes.append(f"panel image suspect: {edges} edge with {'/'.join(others) or 'another input'} "
                             f"changing; ignored (raw DI {raw_hex(snapshot.get('di'))})")
                start = reset = False
        if start:
            notes.append("START edge")
        if reset:
            notes.append("RESET edge")
        mode, pend = self._coincidence(intent, pend, notes, snapshot.get("di"))
        enabling = bool(intent.valid) and (
            was_valid is not True                                            # (re)baseline
            or (mode == panel_core.MANUAL and prior[0] != panel_core.MANUAL)  # selector to MANUAL
            or (arm and prior[2] is not True)                                # Manual Arm on
            or not normal)                                                   # in an emergency
        pend = self._release_first(pend, levels, enabling, notes)
        if arm != self._last_arm:
            if self._last_arm is not None or arm:
                notes.append(f"Manual Arm {'on' if arm else 'off'}")
            self._last_arm = arm
        if intent.valid:
            active = _bit(snapshot.get("di"), config.PANEL_DI_ESTOP) == self.estop_active_high
            self._estop_on = self._estop_on + 1 if active else 0
            self._estop_off = 0 if active else self._estop_off + 1
            if self._estop_active:
                self._estop_active = self._estop_off < self.estop_scans
            else:
                self._estop_active = self._estop_on >= self.estop_confirm_scans
        else:
            self._estop_on = self._estop_off = 0  # blind: the belief holds, the counts restart
        estop_ok = not self._estop_active
        if intent.valid and estop_ok != self._last_estop:
            state = "clear" if estop_ok else "ACTIVE"
            notes.append(f"E-stop signal (DI{config.PANEL_DI_ESTOP:02X}) {state}")
            self._last_estop = estop_ok
        if self.pendant is not None and pend != self._last_pendant:
            held = [n for n in pend._fields if getattr(pend, n)]
            notes.append("pendant " + (" ".join(held).upper() if held else "released"))
            self._last_pendant = pend
        frame = PanelFrame(
            valid=bool(intent.valid),
            mode_auto=mode == panel_core.AUTO,
            start_edge=start,
            reset_edge=reset,
            seq=self.seq,
            comms_ok=comms,
            changed="; ".join(notes) or None,
            pendant=pend,
            manual_arm=arm,
            start_held=bool(intent.valid and intent.start_held),
            reset_held=bool(intent.valid and intent.reset_held),
            acquired=bool(comms),
            link=link,
            link_text=link_text,
            other="; ".join(n for n in notes if n != link_text) or None,
            warn=any(w in n for n in notes if n != link_text for w in _WARN_NOTES),
            estop_ok=estop_ok,
        )
        self._last_frame = frame
        return frame

    def _release_first(self, pend, levels, enabling, notes) -> panel_core.PendantIntent:
        """Mask every direction still waiting to be released since the last enabling event.
        Tracked on the raw LEVELS, not the intent: FWD held, then RVS added, cancels to idle
        in the intent without FWD ever having been let go."""
        if self.pendant is None or levels is None:
            return pend
        held = {n for n, on in zip(pend._fields, levels, strict=True) if on}
        if enabling:
            new = held - self._must_release
            if new:
                notes.append(f"pendant {' '.join(sorted(new)).upper()} held at enable: release it")
            self._must_release |= held
        self._must_release &= held  # read LOW once: released
        if not self._must_release:
            return pend
        return pend._replace(**{n: False for n in self._must_release})

    def _coincidence(self, intent, pend, notes, di=None) -> tuple[str, panel_core.PendantIntent]:
        """The (mode, pendant) to publish this scan, withholding a simultaneous change."""
        if not intent.valid:
            self._held, self._held_for = None, 0
            return intent.mode, pend
        prev_mode = self._last_mode if self._last_mode is not None else intent.mode
        prev_pend = self._last_pendant if self._last_pendant is not None else panel_core.PENDANT_IDLE
        mode_changed = intent.mode != prev_mode
        pend_pressed = any(pend) and pend != prev_pend
        if self._held is None and self.hold_scans > 0 and mode_changed and pend_pressed:
            self._held, self._held_for = (intent.mode, pend), 1
            notes.append(
                f"panel image suspect: selector {intent.mode.upper()} and pendant changed together; withheld"
                f" (raw DI {raw_hex(di)})"
            )
            return prev_mode, panel_core.PENDANT_IDLE
        if self._held is not None:
            if (intent.mode, pend) != self._held:
                self._held, self._held_for = None, 0  # reverted or moved on: it never counted
                notes.append("panel image suspect: cleared")
            else:
                self._held_for += 1
                if self._held_for < self.hold_scans:
                    return prev_mode, panel_core.PENDANT_IDLE
                self._held, self._held_for = None, 0
                notes.append("panel image suspect: persisted, accepted")
        if intent.mode != self._last_mode:
            notes.append(f"selector {intent.mode.upper()}")
            self._last_mode = intent.mode
        return intent.mode, pend


def _bit(di, ch: int) -> bool:
    try:
        return bool(di[ch])
    except (IndexError, TypeError):
        return False


def emergency_event(state: int, prev: int, note: str) -> tuple[str, str, str] | None:
    """The /amr/events entry for an emergency transition (amr_base.emergency), as (severity
    "info" | "warn" | "error", catalogue code, text), or None. `note` is Emergency.step()'s
    "emergency A -> B: why". A blind panel never makes a transition (owner 2026-11-16)."""
    why = note.split(": ", 1)[1] if ": " in note else note
    if state == emergency.ACTIVE:
        return "error", "ESTOP", f"EMERGENCY STOP ({why}): release the E-stop, then press Reset"
    if state == emergency.RESET_NEEDED:
        return "warn", "ESTOP_RESET_NEEDED", "E-stop released: press Reset"
    if state == emergency.RESETTING:
        return "info", "ESTOP", "Reset pressed: waiting for the drives to leave STO"
    if state == emergency.RESET_FAILED:
        return "error", "ESTOP_RESET_FAILED", f"Reset did not take: {why}"
    if state == emergency.NORMAL:
        return "info", "ESTOP", "cleared: emergency stop"
    return None


# AUTO runs that count for the alarm horn: tracked line RUNNING / HOLD, trackless
# EXECUTING / BLOCKED (amr_interfaces LineState / RunState values).
LINE_ACTIVE = (2, 3)
RUN_ACTIVE = (2, 4)
LINE_PREMOVE = 1  # LineState.ARMED: the pre-move warning after a Start
LINE_HOLD = 3  # LineState.HOLD


def alarm_wanted(
    mode_auto: bool, line_state: int | None, run_state: int | None,
    field_fresh: bool, protective_clear: bool, warning_active: bool,
    run_premove: bool = False,
) -> bool:
    """dio.alarm_on (operator, 2026-10-02): AUTO RUNNING and (protective stop, warning 1 or
    warning 2). Field state comes from the mux; stale field data does not sound it.

    And the pre-move warning (2026-10-08): from a Start until the vehicle moves (line ARMED,
    RunState.premove) the alarm horn sounds whatever the fields say, then gives way to the
    movement horn once the wheels turn."""
    if mode_auto and (line_state == LINE_PREMOVE or run_premove):
        return True
    running = mode_auto and (line_state in LINE_ACTIVE or run_state in RUN_ACTIVE)
    return running and field_fresh and (not protective_clear or warning_active)


def call_wanted(mode_auto: bool, line_state: int | None, hold_cause: str, line_fresh: bool) -> bool:
    """The stop call (manuals/stop-call-alarm-plan.md, owner 2026-11-13): the line job is parked in
    a hold that waits for a person to attach or release, then a physical Start. AUTO only, and only
    on a fresh LineState: a line layer that died while parked must not leave the vehicle calling."""
    return bool(mode_auto and line_fresh and line_state == LINE_HOLD and hold_cause in CALL_CAUSES)


def call_phase(now: float, since: float, on_s: float, off_s: float) -> bool:
    """The call's pulse, phase 0 at `since`: on for on_s, off for off_s, repeating. off_s 0 is
    continuous; on_s 0 is no call at all."""
    if on_s <= 0.0:
        return False
    if off_s <= 0.0:
        return True
    return (now - since) % (on_s + off_s) < on_s


def motion_outputs(turning: bool, alarm: bool, channels, movement_horn) -> dict[int, bool]:
    """dio.motion_on with the horn switch (operator, 2026-10-07): while the alarm horn sounds
    (protective, warning 1 or warning 2 in an AUTO run) the movement horn is OFF, so the
    sound changes; the other motion outputs (DO08) keep following the motors."""
    return {ch: turning and not (alarm and ch in movement_horn) for ch in channels}


def coil_image(normal: bool, alarm: bool, turning: bool,
               alarm_on=None, motion_on=None, movement_horn=None) -> dict[int, bool]:
    """Every DIO coil panel_node drives this tick, by channel: dio.alarm_on (DO01, the alarm horn
    with the pre-move warning and the stop-call pulse) and dio.motion_on (DO00 movement horn,
    DO08). While the emergency state is not NORMAL every one is LOW (owner, emergency plan §4)."""
    alarm_on = config.DIO_ALARM_ON if alarm_on is None else alarm_on
    motion_on = config.DIO_MOTION_ON if motion_on is None else motion_on
    movement_horn = config.DIO_MOVEMENT_HORN if movement_horn is None else movement_horn
    outs = {ch: alarm for ch in alarm_on}
    outs.update(motion_outputs(turning, alarm, motion_on, movement_horn))
    return outs if normal else dict.fromkeys(outs, False)


# The motion lamp (dio.motion_on): a wheel turning faster than this is moving (feedback noise
# floor). drive_node fills DriveStatus.turning with wheels_turning() (WP-C7, cpu-load plan C#15).
TURNING_RAD_S = 0.01


def wheels_turning(left_valid: bool, left_rad_s: float, right_valid: bool, right_rad_s: float,
                   floor: float = TURNING_RAD_S) -> bool:
    """Is either motor turning? An invalid side counts as not turning."""
    return bool((left_valid and abs(left_rad_s) > floor) or (right_valid and abs(right_rad_s) > floor))


# /amr/panel_state once per DIO acquisition plus a fallback (WP-C3, cpu-load plan C#8). The node
# ticks at 50 Hz, the DIO scans at 20 Hz: publishing every tick sent each image 2-3 times. An
# acquisition (and with it every Start/Reset edge) goes out on the tick that evaluates it, a frame
# that changed anything too, and otherwise the last frame repeats once FALLBACK_S has passed, so
# consumers with 0.2 s windows never see a gap past one tick after it (<= 60 ms at 50 Hz). While
# Start or Reset is held every tick goes out (rare and short: a press, or the 1 s At home hold).
FALLBACK_S = 0.05


class PublishGate:
    """When to publish a PanelFrame. Clock-fed, no ROS."""

    def __init__(self, fallback_s: float = FALLBACK_S, slack_s: float = 0.001) -> None:
        self.fallback_s = float(fallback_s)
        self.slack_s = float(slack_s)  # a timer's jitter must not push the fallback a whole tick
        self._last: float | None = None

    def due(self, now: float, frame: PanelFrame, force: bool = False) -> bool:
        """force: publish now whatever the frame (panel_node: an emergency state transition, which
        can fall between acquisitions - RESETTING -> NORMAL on a DriveStatus, RESET_FAILED on time)."""
        late = self._last is None or now - self._last >= self.fallback_s - self.slack_s
        # A held Start or Reset goes out every tick: the At home combination (amr_line.home_combo)
        # times the hold on the messages it receives, and a 60 ms gap would show in its latency.
        held = frame.start_held or frame.reset_held
        if force or frame.acquired or frame.changed or frame.start_edge or frame.reset_edge or held or late:
            self._last = now
            return True
        return False
