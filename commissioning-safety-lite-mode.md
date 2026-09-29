# Commissioning: safety-lite mode (branch `slam-safety-lite`)

Build state this checks: no safety PLC. The drives' HWTO/STO inputs are jumpered
(factory condition), EDM is not wired (DI8/DI9 are now spare), and the physical
E-stop cuts drive power directly. The nanoScan3 is on Ethernet only. Manual use only;
AUTO is not commissioned here.

## Before you start

- [ ] Pull the branch on the vehicle PC, then rebuild. `amr_interfaces` changed
      (PanelState got `estop` and `web_buttons`; VirtualPanel is new), so it goes first:
      `colcon build --packages-select amr_interfaces amr_base amr_mission amr_bringup amr_web`
- [ ] `sudo systemctl restart amr.service`, then open the Manual page.
- [ ] Wheels on blocks for tests 1–5. Tests 6–7 are on the floor at 0.20 m/s with a clear area.

**The jog pendant is disconnected.** Tests that need it (1b, 4) are marked
**NOT DONE YET** and are skipped unless someone specifically asks for them to be run.

Needs column: **Human** = someone must act at the vehicle. **Scriptable** = can be
done through the web API or a shell on the vehicle PC (someone still sets the
wheels on blocks and stays in reach). **Pendant** = needs the pendant, NOT DONE YET.

## Tests

| # | Needs | Do | Pass when |
|---|---|---|---|
| 1 | Human | After the restart, look at the **Buttons** panel on the Manual page. Press the physical Start and Reset, and flip the selector. | **Physical panel** is highlighted. Web Start/Reset/selector are greyed out. Each press shows up as a `PANEL` event in the log. |
| 1b | Pendant: **NOT DONE YET** | In physical mode, hold the pendant FWD. | The pendant jogs the wheels. |
| 2 | Scriptable | Click **Web buttons**. | The Selector tile on the left rail reads **MANUAL · web buttons**. No Start or Reset edge is logged when you switch. Jogging with the web pad turns the wheels. |
| 3 | Scriptable | Click **Auto** on the page, then try to jog. Click **Manual** again. | Under Auto the jog does not move the wheels (the mux says "AUTO, no motion permit"). Under Manual, jogging works again. |
| 4 | Pendant: **NOT DONE YET** | Hold the physical pendant FWD, then click **Physical panel** or **Web buttons**. | The switch is refused with "the vehicle is being driven; stop first". |
| 5 | Scriptable | In web mode, with the drives on (Drives tile **ARMED**), press **E-STOP** on the page. Press Reset. Then click **Release E-stop** and press Reset again. | After E-STOP: Selector tile shows **E-STOP** and Drives goes **OFF** within about 1 s. Reset while it is still pressed does nothing. After Release plus Reset, the tile clears and Drives returns to **ARMED** within about 3 s. |
| 6 | Human | On the floor, jog forward at 0.20 m/s with the web pad. Press **E-STOP** on the page while the vehicle is moving. Then do the same in physical-button mode, and clear it with the **physical** Reset. | The vehicle stops on its ramp without a jerk (write down the stopping distance). Clearing works from the physical Reset too. |
| 7 | Human | While jogging with the web pad, hit the **physical E-stop mushroom**. Release it and restore power. | Power is cut and the vehicle stops. After power returns, note how it recovers: drives re-arm by themselves, or the Alarms page shows `DRIVE_ALARM` 8130h and needs a drive power cycle plus Recover. |
| 8 | Scriptable | In web mode, restart the service (`sudo systemctl restart amr.service`). | After the restart the page shows **Physical panel**: it always starts on the physical buttons. |

## Record

| # | Result | Stop distance / notes | Initials |
|---|---|---|---|
| 1 | | | |
| 1b | NOT DONE YET (pendant disconnected) | | |
| 2 | | | |
| 3 | | | |
| 4 | NOT DONE YET (pendant disconnected) | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
