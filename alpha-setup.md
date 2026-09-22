# alpha-setup.md — building the AMR host from a clean Ubuntu 22.04

Provisioning guide for the vehicle PC (`gvipc-evo-01`, NEXCOM Neu-X102-N97) from
a **fresh Ubuntu 22.04 install**: no ROS, no desktop, no network configuration,
GA kernel. At the end the machine boots into `amr.service` (the vehicle) and an
operator kiosk on the panel, exactly as the as-built vehicle does on 2026-09-21.

Written from the running vehicle and the repo. Everything the repo does *not*
carry (kiosk layer, netplan, udev, CAN unit, lightdm, logind, bashrc) is
reproduced here verbatim so this file is self-contained. Sections marked
**RECONSTRUCTED** were derived from the live state (`ip`, `networkctl`,
reference copies) because the originals are root-only; verify them against the
vehicle before trusting them on a second unit (`sudo cat /etc/netplan/*.yaml`).

Order matters. Do the sections top to bottom; each one is a prerequisite of the
next. Total time on a fast uplink: ~1.5 h, most of it apt.

---

## 0. As-built reference

### Host

| | |
|---|---|
| PC | NEXCOM Neu-X102-N97 — Intel N97 (Alder Lake-N, iGPU `8086:46d1`), 4 cores, 8 GB, 98 GB LVM root (`ubuntu--vg/ubuntu--lv`) |
| OS | Ubuntu 22.04 **Server** install (cloud-init netplan, LVM) + `xfce4` added; **HWE kernel 6.8** (`linux-generic-hwe-22.04`) |
| Hostname / user | `gvipc-evo-01` / `gvipc-evo-01` (uid 1000, groups `adm dialout cdrom sudo dip plugdev lxd`); `sudo` asks a password, **no NOPASSWD** anywhere |
| Kiosk user | `amrkiosk` (uid 1001, no password, no sudo, no groups) |
| Repo | `~/agv_can` ← `git@github.com:jmilliaan/gvievo-01.git`, branch `slam-roadmap` (deploy from `main` once merged) |
| Time | `Asia/Jakarta`, chrony (`systemd-timesyncd` masked), RTC in UTC |
| Locale | `en_US.UTF-8` |

**Every path in the units is absolute under `/home/gvipc-evo-01`.** Provisioning
under another username means editing `amr.service` (`User=`, `Group=`,
`WorkingDirectory=`, `EnvironmentFile=`, `ExecStart=`, both `ExecStartPre` owners),
`amr.env`, and `~/.bashrc`. Keep the username unless there is a reason not to.

### Network interfaces

| Interface | Driver | Managed by | Address | Peer |
|---|---|---|---|---|
| `enp2s0` (LAN1) | `igc` (Intel i226, `8086:125c`) | netplan → networkd | `192.168.1.10/24`, no gateway, no DNS | DIO island `192.168.1.30:502` (Modbus TCP), RFID reader `192.168.1.200:2022` |
| `enp3s0` (LAN2) | `igc` | netplan → networkd | `192.168.3.2/24`, no gateway, no DNS | nanoScan3 `192.168.3.10` (CoLa2 TCP 2122, UDP data → host `:6060`) |
| `wlp1s0` | `iwlwifi` (Intel 7260) | NetworkManager | `192.168.2.20/24`, gw `192.168.2.10`, DNS 1.1.1.1/8.8.8.8, metric 700 | SSID `agv_field` — the operator tablet reaches `http://192.168.2.20:5001` here |
| `usb0` | `cdc_ether`/`rndis` | netplan → networkd | DHCP, metric 100 | phone tether: maintenance uplink and remote SSH |
| `can0` | `slcan` (CANable 2.0, USB `16d0:117e`) | `canable@can0.service` | 125 kbps, txqueuelen 1000 | BLV-R node 1 (left), node 2 (right), SICK MLS node 10 |
| `lo` | | | | **all ROS 2 DDS traffic** (loopback-only CycloneDDS) |

Two default routes on purpose (`usb0` metric 100 first, then `wlp1s0` 700). The
two wired LANs never carry a default route — a third would blackhole traffic.
**`nmcli` silently does nothing on the ethernet ports**; they belong to netplan.

### Devices on the vehicle whose addresses are configured *on the device*, not on the PC

| Device | Setting | Tool |
|---|---|---|
| Oriental Motor BLV-R ×2 | CANopen node IDs 1 (left) / 2 (right), 125 kbps, `1016h` volatile | MEXE02 over USB |
| SICK MLS | node ID 10, 125 kbps, TPDO1 `0x18A` @100 Hz track; yaw-rate TPDO disabled | SOPAS / dip switches |
| SICK nanoScan3 | IP `192.168.3.10`; fields, monitoring cases | Safety Designer (read-only for us) |
| Modbus I/O island | IP `192.168.1.30`, unit 1 | vendor web page |
| RFID reader (Chafon) | IP `192.168.1.200`, TCP 2022 | vendor tool |
| Jog pendant / panel | DI1 Start, DI2 Reset, DI3 AUTO/MANUAL, DI4–7 FWD/RVS/LEFT/RIGHT, DO0 horn | wiring, `profiles/agv-01.json` |

Nothing in this guide changes those. The profile (`profiles/agv-01.json`) must
agree with them and is validated at boot; a mismatch is fatal, not silent.

---

## 1. OS baseline

Install Ubuntu Server 22.04 (LVM, OpenSSH server ticked, user `gvipc-evo-01`).
Then, as that user:

```bash
sudo apt update && sudo apt full-upgrade -y

# HWE kernel: the GA 5.15 kernel predates the N97 iGPU and the i226 NIC quirks.
# The vehicle runs 6.8.0-138. Reboot after.
sudo apt install -y linux-generic-hwe-22.04
sudo reboot
```

```bash
sudo hostnamectl set-hostname gvipc-evo-01
sudo timedatectl set-timezone Asia/Jakarta
sudo localectl set-locale LANG=en_US.UTF-8

# Base tooling (git/ssh already present on Server)
sudo apt install -y git curl python3-pip can-utils ethtool net-tools chrony
sudo systemctl enable --now ssh chrony        # chrony masks systemd-timesyncd by itself

# Groups the operator account needs (dialout: bench access to /dev/canable0)
sudo usermod -aG dialout,plugdev "$USER"
```

### Power: the vehicle never sleeps, and the power key does nothing

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

sudo install -d /etc/systemd/logind.conf.d
sudo tee /etc/systemd/logind.conf.d/ignore-power-key.conf >/dev/null <<'X'
[Login]
HandlePowerKey=ignore
X
sudo tee /etc/systemd/logind.conf.d/50-amr.conf >/dev/null <<'X'
# Nothing about the display may ever put the vehicle to sleep or log the
# operator out.
[Login]
HandleLidSwitch=ignore
HandleLidSwitchDocked=ignore
HandleLidSwitchExternalPower=ignore
IdleAction=ignore
KillUserProcesses=no
X
sudo systemctl restart systemd-logind
```

> `HandlePowerKey=ignore` was added during the spurious-shutdown investigation
> (`logs/pwrbtn-watch.sh` samples ACPI counters). Only the first file is on the
> vehicle today; `50-amr.conf` exists in the kiosk staging folder and is the
> intended final state. Install both.

GRUB is stock (`GRUB_TIMEOUT=0`, hidden, no kernel parameters).

---

## 2. Networking

### 2.1 Who manages what

Ubuntu Server ships netplan → `systemd-networkd`. Installing `network-manager`
(needed for Wi-Fi and for the web UI's SSID/dBm readout via `nmcli`) drops in
`/usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf`
(`unmanaged-devices=*,except:type:wifi,...`), which is exactly the split we want:
**NM owns Wi-Fi only; netplan/networkd owns every wired port.**

```bash
sudo apt install -y network-manager
sudo systemctl enable --now NetworkManager

# amr.service is After=network-online.target. networkd's wait-online would block
# ~2 min on any unplugged wired port; NM's nm-online is the one we want (it
# returns once agv_field is up or ~30 s have passed).
sudo systemctl mask systemd-networkd-wait-online.service
sudo systemctl enable NetworkManager-wait-online.service
```

Wi-Fi power save is left at the Ubuntu default (`wifi.powersave = 3` in
`/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf`).

### 2.2 netplan — the wired ports and the tether

All four files are `root:root 0600`. `renderer: networkd` is scoped **inside**
the `ethernets:` block on purpose (see `manuals/obsolete/rfid-setup/rfid-link-notes.txt`
§1): if cloud-init ever regenerates `50-cloud-init.yaml` with a global renderer, a
scoped one cannot fight it and take Wi-Fi down.

`/etc/netplan/50-cloud-init.yaml` — **RECONSTRUCTED** (the installer's file; on the
vehicle it was last edited 2026-09-21 and is 354 bytes). Keep the installer's
file and only make sure it does not claim `enp2s0`/`enp3s0` with DHCP. The stock
content is close to:

```yaml
# This file is generated from information provided by the datasource.  Changes
# to it will not persist across an instance reboot.  To disable cloud-init's
# network configuration capabilities, write a file
# /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg with the following:
# network: {config: disabled}
network:
  version: 2
```

`/etc/netplan/55-usb-tether.yaml` — **RECONSTRUCTED** (141 bytes on the vehicle;
`usb0` shows `proto dhcp ... metric 100`, `networkctl` says `configured`):

```yaml
network:
  version: 2
  ethernets:
    renderer: networkd
    usb0:
      dhcp4: true
      optional: true
```

`/etc/netplan/60-rfid-lan1.yaml` — **exact**, the tracked reference copy is
`manuals/obsolete/rfid-setup/60-rfid-lan1.yaml`:

```yaml
# LAN1 (enp2s0) -> RFID reader at 192.168.1.200
#
# Link-local subnet ONLY. Deliberately no gateway4/routes and no nameservers:
# this box already has two default routes (usb0, wlp1s0) and this interface
# must never compete with them. The reader is a direct peer on 192.168.1.0/24.
#
# optional: true  -> boot does not block waiting for this link if the
#                    reader is unplugged or powered off.
network:
  version: 2
  ethernets:
    renderer: networkd
    enp2s0:
      dhcp4: no
      dhcp6: no
      addresses:
        - 192.168.1.10/24
      optional: true
```

`/etc/netplan/70-nanoscan3.yaml` — **RECONSTRUCTED** (627 bytes on the vehicle,
same shape as LAN1; addresses from `nanoscan3.yaml` and `profiles/agv-01.json`):

```yaml
# LAN2 (enp3s0) -> SICK nanoScan3 at 192.168.3.10
# Host 192.168.3.2 receives the UDP scan stream on :6060 (sick_safetyscanners2)
# and opens CoLa2 on the scanner's TCP 2122. No gateway, no DNS: link-local peer.
network:
  version: 2
  ethernets:
    renderer: networkd
    enp3s0:
      dhcp4: no
      dhcp6: no
      addresses:
        - 192.168.3.2/24
      optional: true
```

Install and apply (from the **local console** — a mistake here can drop the tether):

```bash
sudo install -m 600 -o root -g root 55-usb-tether.yaml 60-rfid-lan1.yaml 70-nanoscan3.yaml /etc/netplan/
sudo netplan generate && sudo netplan apply
ip -br addr                 # enp2s0 192.168.1.10, enp3s0 192.168.3.2
ip route                    # NO "default via ... enp2s0/enp3s0"
networkctl list             # enp2s0/enp3s0 "configured", wlp1s0 "unmanaged" (NM's)
```

The `WARNING: Cannot call Open vSwitch` line from netplan is benign.

Port assignment was determined by **carrier and ARP, not by the case label**;
if a rebuilt vehicle has the cables the other way round, swap the interface
names in the two files rather than re-cabling. `manuals/obsolete/rfid-setup/rfid-test.sh`
is the non-destructive probe for that.

### 2.3 Wi-Fi — `agv_field`

```bash
sudo nmcli con add type wifi con-name agv-net ifname wlp1s0 ssid agv_field \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk '<PSK>' \
  ipv4.method manual ipv4.addresses 192.168.2.20/24 ipv4.gateway 192.168.2.10 \
  ipv4.dns 1.1.1.1,8.8.8.8 ipv4.route-metric 700 \
  connection.autoconnect yes connection.autoconnect-priority 10 connection.autoconnect-retries 0
nmcli con up agv-net
```

The vehicle does **not** need Wi-Fi or the internet to run. ROS is loopback-only,
the scanner and I/O island are wired, the kiosk browser talks to `127.0.0.1`.
Wi-Fi is how the tablet reaches the pages and how the header shows link quality.

---

## 3. CAN — the CANable 2.0 as `can0`

The adapter runs slcan firmware and shows up as a CDC-ACM tty. A udev rule pins
it to `/dev/canable0` **by USB serial** and pulls in a templated unit that runs
`slcand` in the foreground and brings `can0` up at 125 kbps. `amr.service`
`BindsTo=sys-subsystem-net-devices-can0.device`, so unplugging the adapter stops
the vehicle stack and re-plugging brings both back.

`/etc/udev/rules.d/70-canable.rules` — change `ATTRS{serial}` to the new
adapter's serial (`udevadm info -a /dev/ttyACM0 | grep serial`):

```udev
# MKS / Openlight Labs CANable 2.0 (slcan firmware) -> stable /dev/canable0
# Matched by USB serial, so the symlink follows the adapter across USB ports
# and regardless of which ttyACM index it lands on.
# ACTION!="remove" (not =="add"): snapd and `udevadm trigger` re-send
# "change" events for every device; an add-only rule then loses the symlink,
# which cascades into stopping canable@can0 and amr.service (seen 2026-09-17).
SUBSYSTEM=="tty", ACTION!="remove", \
  ATTRS{idVendor}=="16d0", ATTRS{idProduct}=="117e", ATTRS{serial}=="2087327F5548", \
  SYMLINK+="canable0", MODE="0660", GROUP="dialout", ENV{ID_MM_DEVICE_IGNORE}="1", \
  TAG+="systemd", ENV{SYSTEMD_WANTS}="canable@can0.service"
```

`/etc/systemd/system/canable@.service`:

```ini
[Unit]
Description=CANable slcan bridge -> SocketCAN %i (125 kbps)
BindsTo=dev-canable0.device
After=dev-canable0.device

[Service]
Type=simple
# -s4 = 125 kbps. -F keeps slcand in the foreground so systemd can supervise it.
ExecStart=/usr/bin/slcand -o -c -f -s4 -F /dev/canable0 %i
# slcand creates the netdev asynchronously; wait for it, then configure.
ExecStartPost=/bin/sh -c 'for i in $(seq 50); do ip link show %i >/dev/null 2>&1 && break; sleep 0.1; done; ip link set dev %i txqueuelen 1000 up'
ExecStopPost=-/sbin/ip link set dev %i down
Restart=no

[Install]
WantedBy=multi-user.target
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=tty
sudo systemctl daemon-reload
# Do NOT `systemctl enable canable@can0` — udev's SYSTEMD_WANTS starts it when the
# device appears (as-built: "disabled" enable state, started by the device).
ls -l /dev/canable0                     # -> ttyACMn
systemctl status canable@can0 --no-pager
ip -d link show can0                    # state UP, qlen 1000
candump -n 5 can0                       # frames flow once the drives are powered
```

`ENV{ID_MM_DEVICE_IGNORE}="1"` stops ModemManager AT-probing the port at plug-in
(the `.ADDITION` note in the staging folder — already folded into the rule above).

---

## 4. ROS 2 Humble

```bash
sudo apt install -y software-properties-common && sudo add-apt-repository -y universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu jammy main" | sudo tee /etc/apt/sources.list.d/ros2.list
sudo apt update

sudo apt install -y \
  ros-humble-ros-base python3-colcon-common-extensions python3-rosdep python3-vcstool \
  ros-humble-rmw-cyclonedds-cpp \
  ros-humble-navigation2 ros-humble-nav2-bringup \
  ros-humble-slam-toolbox ros-humble-robot-localization \
  ros-humble-sick-safetyscanners2 \
  ros-humble-robot-state-publisher ros-humble-xacro \
  ros-humble-foxglove-bridge ros-humble-teleop-twist-keyboard ros-humble-tf2-tools \
  ros-humble-launch-testing ros-humble-launch-testing-ros \
  ros-humble-ament-lint-auto ros-humble-ament-lint-common \
  ros-humble-ament-copyright ros-humble-ament-flake8 ros-humble-ament-pep257

sudo rosdep init; rosdep update
```

The vehicle uses the **`ros2.sources`** (deb822) form of the apt source; the
`.list` form above is equivalent. No `ros-humble-desktop`: nothing on the vehicle
needs rviz/rqt. The as-built machine has 265 `ros-humble-*` packages, all pulled
in by the list above.

**DDS is CycloneDDS, loopback-only.** The config file is in the repo
(`amr_ws/src/amr_bringup/config/cyclonedds-local.xml`, binds `lo`, no multicast,
unicast discovery over 120 participant slots). Every shell and the service point
`CYCLONEDDS_URI` at it (section 5.3). Vehicle domain is **10**, sim **20**; the
launch files enforce it.

---

## 5. The repo, Python deps, shell environment, build

### 5.1 Clone

```bash
cd ~ && git clone git@github.com:jmilliaan/gvievo-01.git agv_can    # needs the deploy key in ~/.ssh
cd ~/agv_can && git checkout slam-roadmap                            # or main
```

Two directories outside the repo are created by the service's `ExecStartPre`
lines, but making them now lets you run tests before the first start:

```bash
install -d ~/amr_maps ~/.amr          # AMR_MAPS_DIR (map bundles), AMR_STATE_DIR (logs, evidence, operations.jsonl)
```

### 5.2 Python dependencies

`pyproject.toml` pins nothing on purpose (the offline test suite must run on a
dev box without them). The vehicle uses **user-site pip** for the runtime
libraries; apt provides the rest. Versions as of 2026-09-21:

| Package | Version | From | Used by |
|---|---|---|---|
| `python-can` | 4.6.1 | pip --user | `agv_core.drivers.canbus`, `amr_base.canopen` |
| `pymodbus` | 3.15.0 | pip --user | `agv_core.drivers.dio` (I/O island) |
| `flask` | 3.1.3 (werkzeug 3.1.8) | pip --user | `amr_web` |
| `numpy` | 2.2.6 | pip --user (overrides apt 1.21.5) | maps, routes, scan checks |
| `opencv-python-headless` | 5.0.0.93 | pip --user | `amr_tools` mask painting |
| `pyserial` | 3.5 | apt `python3-serial` | bench tools |
| `PyYAML` | 5.4.1 | apt `python3-yaml` | bundles, params |
| `psutil` | 5.9.0 | apt | supervisor |
| `pytest` | 6.2.5 | apt `python3-pytest` | tests (`conftest.py` exists *because* this pytest predates `pythonpath`) |
| `ruff` | 0.16.7 | pip --user | lint |

```bash
sudo apt install -y python3-serial python3-yaml python3-psutil python3-pytest python3-numpy
pip3 install --user python-can==4.6.1 pymodbus==3.15.0 flask==3.1.3 numpy==2.2.6 \
                    opencv-python-headless ruff
```

> **Known, accepted conflict:** user-site numpy 2.x breaks the system
> `cv_bridge` (built on numpy 1.21). Nothing in this project imports `cv_bridge`
> (no camera). Do not "fix" it by downgrading numpy; `amr_tools` needs the pair.

`~/.bashrc` already gets `~/.local/bin` on `PATH` in the block below. Node.js
(nodesource), bun and deno are on the vehicle for screenshot tooling
(`.shots/`) only; they are **not** runtime dependencies — skip them.

### 5.3 `~/.bashrc` — the vehicle shell environment

Append (this is what `amr-launch.sh` / `amr-supervisor.sh` do for the service;
an interactive shell must match or `amr_interfaces` messages will not decode
and nothing will discover):

```bash
export PATH="$HOME/.local/bin:$PATH"
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
[ -f ~/agv_can/amr_ws/install/setup.bash ] && source ~/agv_can/amr_ws/install/setup.bash
# Vehicle ROS domain + loopback-only DDS (amr_ws/README.md "ROS domain / DDS scope").
# For simulation work in a shell: source ~/agv_can/amr_ws/env/sim.sh
[ -f ~/agv_can/amr_ws/env/vehicle.sh ] && source ~/agv_can/amr_ws/env/vehicle.sh
```

`env/vehicle.sh` (in the repo) sets `ROS_DOMAIN_ID=10`, `RMW_IMPLEMENTATION`,
`CYCLONEDDS_URI=file://$HOME/agv_can/amr_ws/src/amr_bringup/config/cyclonedds-local.xml`
and puts `$HOME/agv_can` on `PYTHONPATH` so `agv_core` imports from the colcon
install space. `AGV_PROFILE` is unset → `profiles/agv-01.json`.

### 5.4 Build and test

```bash
source ~/.bashrc
cd ~/agv_can/amr_ws
rosdep install --from-paths src --ignore-src -y --skip-keys "python3-can python3-flask"   # sanity: should be a no-op
colcon build --symlink-install
source install/setup.bash

# Offline checks — no hardware, ~1 min
cd ~/agv_can && python3 tests/run_all.py                            # 531 checks, count is pinned
cd ~/agv_can/amr_ws && env AMR_SIM_TESTS=0 ROS_DOMAIN_ID=89 python3 -m pytest -q src/*/test
ruff check ~/agv_can/agv_core ~/agv_can/tests && (cd ~/agv_can/amr_ws && ruff check src)
```

`PackageNotFoundError` after adding a package = re-source, not a bug.

---

## 6. `amr.service` — the vehicle

The repo carries the unit and its helpers under `amr_ws/deploy/`:

| File | Role |
|---|---|
| `amr.service` | the **only** application boot unit; `BindsTo` can0; `EnvironmentFile=amr.env`; `ExecStartPre` creates `/run/lock/amr` (1777), `~/.amr`, `~/amr_maps`; `KillSignal=SIGINT`, `TimeoutStopSec=55`; `Restart=on-failure` 3×/60 s |
| `amr.env` | `AMR_MAPS_DIR`, `AMR_STATE_DIR`, feature flags `AMR_WEB/AMR_FOXGLOVE/AMR_LIDAR=true`, `AMR_LOC_BLANK_DYNAMIC=false`. **Paths and switches only; boot never selects a map or resumes a job.** |
| `amr-supervisor.sh` | `ExecStart`: sources ROS + overlay + `env/vehicle.sh`, runs `amr_bringup.supervisor_node -p real:=true ...` |
| `amr-launch.sh` | the same overlay for `ros2 launch` children; exports `PYTHONPATH=<repo root>` |
| `validate.sh` | no-side-effect check: paths, `bash -n`, `systemd-analyze verify`, every `${VAR}` in Exec lines defined in `amr.env`, `agv_core/` present |
| `install.sh` | backs up `/etc/systemd/system/amr.service` to `/var/backups/amr-units/<ts>/`, installs, `daemon-reload`. **Never enables/starts anything** (enforced by `validate.sh`). |

```bash
cd ~/agv_can/amr_ws
./deploy/validate.sh                     # "deployment validation passed"
sudo ./deploy/install.sh                 # prints the backup path
systemctl is-enabled amr                 # disabled — install.sh does not enable
```

Cutover is a **witnessed** step (RUNBOOK §5–§6): E-stop engaged, a person at the
vehicle, drives powered, `can0` up, scanner and I/O island reachable.

```bash
ping -c1 192.168.1.30 && ping -c1 192.168.3.10          # DIO island, scanner
python3 -m agv_core.drivers.canbus.verify_bus            # nodes 1, 2, 10 answer (service stopped)
sudo systemctl enable --now amr.service
journalctl -u amr.service -f                             # reaches IDLE; web on :5001
```

Boot check (RUNBOOK §1): Status page Mode `IDLE`, Selector `MANUAL`/`AUTO` not
`STALE`, Drives `ARMED`/`OFF` without a red bar, Command `none`. A profile with
`"tracked": true` enters `LINE` by itself after IDLE.

What the supervisor owns from here: `base.launch.py real:=true` (drive_node =
`can0` owner, panel_node = I/O island owner, nanoScan3 driver, mux, odom, EKF),
`amr_web.web_node` on `0.0.0.0:5001`, `foxglove_bridge` on `:8765`, and one
mode layer at a time. Bench tools take the `/run/lock/amr` owner lock and refuse
while the service holds it — **stop the service before any bench work.**

---

## 7. The operator display — XFCE (maintenance) + kiosk (production)

Design: LightDM autologs the unprivileged **`amrkiosk`** account into a bare X
session (`matchbox-window-manager` + Chromium `--kiosk` on `http://127.0.0.1/`,
which nginx proxies to `:5001` and replaces with a holding page while
`amr.service` is down). XFCE stays installed as the *maintenance* session for
`gvipc-evo-01`. The vehicle stack is `multi-user.target` and has **no** dependency
on the display: Xorg can crash, blank or have zero outputs with no path to
`can0`, the island or the scanner (see `~/xfce-kiosk-staging/README-seamless.md`).

The panel is a 6–7" touch display (Goodix `27c6:0818`, works with stock
`hid-multitouch`) at ~1280×720 CSS px; `amr_web` scales for it via `data-ui`.

> These files live in `~/xfce-kiosk-staging/` on the vehicle, **outside the
> repo**, and mirror their destination paths. Their content is reproduced here
> in full. The live `amr-kiosk-session` has one line the staging copy lacks
> (`unclutter`); this document shows the live version.

### 7.1 Packages

```bash
sudo apt install -y --no-install-recommends \
  xfce4 xfce4-session xfce4-terminal lightdm lightdm-gtk-greeter \
  xserver-xorg-core x11-xserver-utils \
  matchbox-window-manager nginx-light unclutter curl
# Do NOT install xserver-xorg-video-intel (legacy DDX is unreliable on Alder Lake-N;
# the xorg.conf.d file below forces modesetting) and do NOT install xfce4-power-manager
# (blanking is disabled at the X server level instead).

sudo snap install chromium
sudo snap refresh --hold chromium          # a snap refresh must never restart the kiosk under the operator
```

Pick `lightdm` when debconf asks for the default display manager.

### 7.2 Kiosk account

```bash
sudo adduser --disabled-password --gecos "Operator Display" amrkiosk
```

### 7.3 nginx front door

`/etc/nginx/sites-available/amr-kiosk`:

```nginx
# Front door for the operator display. The browser points here (:80), never
# at :5001, so it never sees a connection error: when amr.service is down,
# nginx serves the holding page instead, which auto-refreshes until the
# real UI answers.
server {
    listen 127.0.0.1:80 default_server;
    server_name _;

    location = /amr-waiting.html {
        root /var/www/amr;
        add_header Cache-Control "no-store";
    }

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 2s;
        proxy_read_timeout 60s;
        proxy_intercept_errors on;
        error_page 502 503 504 =200 /amr-waiting.html;
    }
}
```

`/var/www/amr/amr-waiting.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>AMR</title>
<meta http-equiv="refresh" content="3">
<style>
 html,body{height:100%;margin:0;background:#111;color:#eee;font-family:sans-serif;
           display:flex;align-items:center;justify-content:center;text-align:center}
 h1{font-size:6vw;margin:0 0 .3em}
 p{font-size:2.5vw;color:#aaa;margin:0}
 .dot{display:inline-block;width:1.2vw;height:1.2vw;border-radius:50%;background:#f90;
      margin-right:.6vw;animation:b 1s infinite}
 @keyframes b{50%{opacity:.2}}
</style></head>
<body><div><h1><span class="dot"></span>AMR system starting</h1>
<p>Waiting for the vehicle controller (amr.service)…</p></div></body></html>
```

```bash
sudo ln -sf /etc/nginx/sites-available/amr-kiosk /etc/nginx/sites-enabled/amr-kiosk
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl enable --now nginx
curl -s http://127.0.0.1/ | head -3        # holding page while amr.service is down
```

If the web port ever changes, change it in **one** place: this nginx file.

### 7.4 Session scripts (`/usr/local/bin`, mode 755, root-owned)

`/usr/local/bin/amr-kiosk-session`:

```bash
#!/bin/bash
# Bare X session for the operator display. No desktop, no panel: a window
# manager that only knows fullscreen, the display hot-plug watcher, and the
# browser supervisor. LightDM autologs the "amrkiosk" user into this.
xset s off; xset s noblank; xset -dpms
/usr/local/bin/amr-display-hotplug.sh &
unclutter -idle 1 -root &
matchbox-window-manager -use_titlebar no -use_cursor yes &
exec /usr/local/bin/amr-kiosk-browser
```

`/usr/local/bin/amr-kiosk-browser`:

```bash
#!/bin/bash
# Keeps exactly one Chromium kiosk window on the AMR UI, forever.
#  - exits for any reason (Alt+F4, Ctrl+W, crash, OOM)  -> respawned in 1 s
#  - navigated off 127.0.0.1, or extra tabs/windows      -> killed, respawned
#  - screen geometry changed (monitor hot-plugged)       -> killed, respawned so
#    the window re-fits the new panel size
URL=http://127.0.0.1/
DBG=9222
export DISPLAY=${DISPLAY:-:0}

geometry() { xrandr -q 2>/dev/null | awk '/current/{print $8 $9 $10}'; }

watchdog() {   # $1 = chromium pid
  sleep 15                             # first start can be slow (snap)
  local g0; g0=$(geometry)
  while kill -0 "$1" 2>/dev/null; do
    sleep 5
    if [ "$(geometry)" != "$g0" ]; then
      logger -t amr-kiosk "screen geometry changed -> restarting browser"
      kill "$1"; return
    fi
    # Ask Chromium what it is showing. Only real tabs (type "page") count;
    # the endpoint also lists internal helpers (chrome://omnibox-popup...)
    # that are not windows. Exactly one tab, on our origin, or it dies.
    read -r pages bad < <(curl -s --max-time 2 "http://127.0.0.1:$DBG/json" | python3 -c '
import json,sys
try: t=[x for x in json.load(sys.stdin) if x.get("type")=="page"]
except Exception: print("? ?"); sys.exit()
print(len(t), sum(1 for x in t if not x.get("url","").startswith("http://127.0.0.1")))')
    if [ "$pages" = "?" ]; then continue; fi        # endpoint not answering: judge next round
    if [ "${pages:-0}" != "1" ] || [ "${bad:-0}" != "0" ]; then
      logger -t amr-kiosk "browser state wrong (pages=$pages off-origin=$bad) -> restarting"
      kill "$1"; return
    fi
  done
}

while :; do
  chromium \
    --kiosk --incognito --noerrdialogs --no-first-run --disable-infobars \
    --disable-session-crashed-bubble --disable-translate --disable-pinch \
    --overscroll-history-navigation=0 --disable-features=TranslateUI \
    --check-for-update-interval=31536000 --password-store=basic \
    --autoplay-policy=no-user-gesture-required \
    --remote-debugging-port=$DBG --remote-allow-origins=* \
    --window-position=0,0 --start-fullscreen \
    "$URL" >/dev/null 2>&1 &
  pid=$!
  watchdog "$pid" &
  wait "$pid"
  logger -t amr-kiosk "chromium exited ($?) -> respawn"
  sleep 1
done
```

`/usr/local/bin/amr-display-hotplug.sh`:

```bash
#!/bin/bash
# Keeps the AMR display "seamless": whatever is plugged in lights up, whatever
# is unplugged is dropped, without anyone touching the robot.
#
# Two triggers, both unprivileged:
#   1. udev DRM events  - instant, when the panel asserts hot-plug-detect (HPD)
#   2. a 5 s poll       - for panels/adapters/extenders that never assert HPD.
#      `xrandr -q` forces the kernel to re-probe every connector (EDID read),
#      so it works even when /sys/class/drm/*/status is stale.
# Outputs are only reconfigured when the set of connected outputs CHANGES, so
# a stable display is never flickered by the poll.
#
# The robot stack (amr*.service) is a separate multi-user.target branch and is
# never touched by anything here.

export DISPLAY=${DISPLAY:-:0}
POLL=5

connected() { xrandr -q 2>/dev/null | awk '$2=="connected"{print $1}' | sort | tr '\n' ' '; }

apply() {
  # --auto enables every connected output at its preferred mode and turns
  # off the disconnected ones. Retry once: EDID can lag the HPD by ~1 s.
  xrandr --auto >/dev/null 2>&1 || { sleep 1; xrandr --auto >/dev/null 2>&1; }
}

last="$(connected)"
apply

# Trigger 1: udev events -> write a token into the FIFO the loop below reads.
fifo=$(mktemp -u /tmp/amr-hotplug.XXXXXX); mkfifo "$fifo"
trap 'rm -f "$fifo"; kill 0' EXIT
( udevadm monitor --udev --subsystem-match=drm 2>/dev/null | while read -r _; do echo u; done > "$fifo" ) &

# Trigger 2: timer.
( while sleep "$POLL"; do echo t; done > "$fifo" ) &

while read -r _ < "$fifo"; do
  sleep 1                         # let the connector settle
  now="$(connected)"
  if [ "$now" != "$last" ]; then
    logger -t amr-display "outputs changed: [$last] -> [$now]"
    apply
    last="$(connected)"
  fi
done
```

`/usr/share/xsessions/amr-kiosk.desktop`:

```ini
[Desktop Entry]
Name=AMR Kiosk
Comment=Fullscreen AMR operator display
Exec=/usr/local/bin/amr-kiosk-session
Type=Application
```

```bash
sudo install -m 755 amr-kiosk-session amr-kiosk-browser amr-display-hotplug.sh /usr/local/bin/
sudo install -m 644 amr-kiosk.desktop /usr/share/xsessions/
```

### 7.5 Chromium policy — `/etc/chromium/policies/managed/amr-kiosk.json`

```json
{
  "URLBlocklist": ["*"],
  "URLAllowlist": ["127.0.0.1", "localhost"],
  "HomepageLocation": "http://127.0.0.1/",
  "NewTabPageLocation": "http://127.0.0.1/",
  "RestoreOnStartup": 4,
  "RestoreOnStartupURLs": ["http://127.0.0.1/"],
  "DeveloperToolsAvailability": 2,
  "ExtensionInstallBlocklist": ["*"],
  "DownloadRestrictions": 3,
  "PromptForDownloadLocation": false,
  "AllowFileSelectionDialogs": false,
  "PrintingEnabled": false,
  "PasswordManagerEnabled": false,
  "SavingBrowserHistoryDisabled": true,
  "TranslateEnabled": false,
  "BrowserSignin": 0,
  "SyncDisabled": true,
  "MetricsReportingEnabled": false,
  "DefaultNotificationsSetting": 2,
  "DefaultGeolocationSetting": 2,
  "AudioCaptureAllowed": false,
  "VideoCaptureAllowed": false,
  "BrowserAddPersonEnabled": false,
  "BrowserGuestModeEnabled": false,
  "TaskManagerEndProcessEnabled": false,
  "BackgroundModeEnabled": false,
  "ShowHomeButton": false,
  "BookmarkBarEnabled": false
}
```

```bash
sudo install -d /etc/chromium/policies/managed
sudo install -m 644 amr-kiosk.json /etc/chromium/policies/managed/
```

If the snap ignores it (Ctrl+T on a USB keyboard opens a real new-tab page),
also place a copy at `/var/snap/chromium/current/policies/managed/`.

### 7.6 Xorg — never blank, no VT switch, modesetting driver

`/etc/X11/xorg.conf.d/10-amr-noblank.conf`:

```conf
# Server-level: never blank, never DPMS-off. Survives session crashes and
# does not depend on xfce4-power-manager (deliberately NOT installed).
Section "ServerFlags"
    Option "BlankTime"   "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime"     "0"
    Option "DontVTSwitch" "true"
    Option "DontZap"      "true"
EndSection

Section "Monitor"
    Identifier "Monitor0"
    Option "DPMS" "false"
EndSection

# Force the generic KMS driver. Do NOT install xserver-xorg-video-intel:
# the legacy intel DDX would otherwise be auto-selected and is unreliable
# on Alder Lake-N.
Section "Device"
    Identifier "Intel-N97"
    Driver     "modesetting"
    Option     "AccelMethod" "glamor"
    Option     "TearFree"    "true"
EndSection
```

### 7.7 LightDM — autologin into the kiosk

`/etc/lightdm/lightdm.conf.d/50-amr-autologin.conf`:

```ini
# Operator display: autologin the unprivileged kiosk account into the bare
# AMR Kiosk session. XFCE remains installed as the maintenance session for
# gvipc-evo-01 (see README-kiosk.md, "Maintenance").
[Seat:*]
autologin-user=amrkiosk
autologin-user-timeout=0
autologin-session=amr-kiosk
user-session=xfce
greeter-hide-users=true
xserver-command=X -core -nolisten tcp
session-cleanup-script=/bin/sh -c 'sleep 2; systemctl restart lightdm'
```

`/etc/systemd/system/lightdm.service.d/override.conf`:

```ini
# Stock unit already has Restart=always; this caps a crash loop so the
# display is retried forever instead of tripping the start-rate limit.
[Unit]
StartLimitIntervalSec=0
[Service]
RestartSec=3
```

```bash
sudo install -d /etc/lightdm/lightdm.conf.d /etc/systemd/system/lightdm.service.d /etc/X11/xorg.conf.d
sudo install -m 644 50-amr-autologin.conf /etc/lightdm/lightdm.conf.d/
sudo install -m 644 override.conf        /etc/systemd/system/lightdm.service.d/
sudo install -m 644 10-amr-noblank.conf  /etc/X11/xorg.conf.d/
sudo systemctl daemon-reload
sudo systemctl enable lightdm && sudo systemctl set-default graphical.target
sudo systemctl restart lightdm
```

Verify:

```bash
journalctl -t amr-kiosk -t amr-display -f            # supervisor + hotplug log, no restart loop
pgrep -a chromium | head -1                          # running as amrkiosk
curl -s http://127.0.0.1:9222/json | grep url        # exactly one page, http://127.0.0.1/
```

Escape tests (USB keyboard on the vehicle): Alt+F4 / Ctrl+W / Ctrl+Q → UI back
< 1 s; Ctrl+T / Ctrl+N → blocked page / killed; F11, Esc, Ctrl+Alt+F1..F6,
Ctrl+Alt+Backspace, Alt+Tab, Super → nothing; `sudo systemctl stop amr` → holding
page within 3 s; unplug/replug monitor → UI back at native size; `pkill -9 chromium`
→ ~2 s; `pkill -9 Xorg` → ~5 s.

### 7.8 XFCE maintenance session (one-time, optional)

To get a desktop on the vehicle's own screen, flip the autologin to
`gvipc-evo-01` / `xfce`, and flip it back when done. **Ctrl+Alt+Fn does not
work on the vehicle by design**; SSH is the intended maintenance path.

```bash
sudo sed -i 's/^autologin-user=.*/autologin-user=gvipc-evo-01/; s/^autologin-session=.*/autologin-session=xfce/' \
    /etc/lightdm/lightdm.conf.d/50-amr-autologin.conf
sudo systemctl restart lightdm
```

Inside that XFCE session, once, to make it deterministic and quiet
(`~/xfce-kiosk-staging/home/.local/bin/amr-xfce-settings.sh`):

```bash
xfconf-query -c xfwm4  -p /general/use_compositing -n -t bool -s false   # fewer moving parts
xfconf-query -c displays -p /Notify -n -t bool -s false                  # no "new display" popup on hotplug
xfconf-query -c displays -p /AutoEnableProfiles -n -t bool -s true
xfconf-query -c xfce4-session -p /general/SaveOnExit -n -t bool -s false # deterministic session every boot
xfconf-query -c xfce4-session -p /general/PromptOnLogout -n -t bool -s false
xfconf-query -c xfce4-desktop -p /desktop-icons/style -n -t int -s 0     # bare desktop
xfconf-query -c xfce4-session -p /shutdown/ShowSuspend  -n -t bool -s false
xfconf-query -c xfce4-session -p /shutdown/ShowHibernate -n -t bool -s false
xfconf-query -c xfce4-session -p /shutdown/ShowHybridSleep -n -t bool -s false
```

and, so the XFCE session also survives monitor hot-plug, the same watcher as a
user autostart — `~/.local/bin/amr-display-hotplug.sh` (copy of the script in
7.4) plus `~/.config/autostart/amr-display-hotplug.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=AMR display hotplug
Exec=/home/gvipc-evo-01/.local/bin/amr-display-hotplug.sh
X-GNOME-Autostart-enabled=true
NoDisplay=true
```

---

## 8. Boot sequence — what depends on what

| Order | Unit / actor | Provides | Blocks the next? |
|---|---|---|---|
| 1 | kernel + udev | `enp2s0/enp3s0/wlp1s0/usb0`; `/dev/canable0` symlink → `SYSTEMD_WANTS=canable@can0` | |
| 2 | `systemd-networkd` (netplan) | wired addresses; all `optional: true` so unplugged peers do not block | no (`systemd-networkd-wait-online` masked) |
| 3 | `NetworkManager` + `nm-online` | `agv_field`; `network-online.target` after link or ~30 s | yes, bounded |
| 4 | `canable@can0.service` | `slcand` + `can0` UP @125 kbps → `sys-subsystem-net-devices-can0.device` | yes — `amr.service` `BindsTo` it |
| 5 | `nginx` | `:80` holding page | no |
| 6 | `amr.service` | lock dir, state/maps dirs, supervisor → base (can0, DIO, scanner), web `:5001`, foxglove `:8765`; **IDLE** | |
| 7 | `lightdm` → `amr-kiosk-session` | Chromium on `http://127.0.0.1/`; independent of 6 | |

Stop path: `systemctl stop amr` sends SIGINT → supervisor revokes lease, stops
the mode layer, disarms drives (zero RPDO, `1016h=0`, Shutdown, NMT Pre-op),
drops the horn coil, then web/bridge; systemd kills the cgroup after 55 s if that
hangs. The kiosk shows the holding page within 3 s.

---

## 9. Acceptance after a fresh build

Run all of these once, in order, before the vehicle leaves the bench.

1. **Cold boot with the monitor unplugged.** `systemctl status amr lightdm canable@can0 nginx` all `active`. Plug the monitor in after 2 min → UI appears, full-screen, native size.
2. **`ip route`** shows exactly two defaults (`usb0` 100, `wlp1s0` 700) and none via the wired ports. `networkctl list` shows `enp2s0/enp3s0 configured`, `wlp1s0 unmanaged`.
3. **Peers**: `ping -c3 -I enp2s0 192.168.1.30`, `ping -c3 -I enp2s0 192.168.1.200`, `ping -c3 -I enp3s0 192.168.3.10` all 0 % loss.
4. **CAN** (service stopped): `candump -n 20 can0` shows TPDOs from `0x181/0x182` and `0x18A`; `python3 -m agv_core.drivers.canbus.verify_bus` → nodes 1, 2, 10 answer; `verify_drivers` → BLV-R identity.
5. **Bench tools refuse while the service runs** (`/run/lock/amr` owner named in the error).
6. **`amr.service` reaches IDLE** (RUNBOOK §1 boot check) with `journalctl -u amr.service` free of tracebacks; `pgrep -af 'amr_|nav2|slam_toolbox|foxglove'` empty after `systemctl stop amr`.
7. **Panel**: on the I/O page each Start/Reset press produces one edge, the selector tracks, a held Start produces one edge (RUNBOOK T12).
8. **Scanner**: `ros2 topic hz /scan` ≈ 34 Hz; `/output_paths` publishes; contamination warning absent.
9. **Kiosk escape table** (7.7) passes; `sudo pkill -9 Xorg` does not touch `amr.service` (`journalctl -u amr -u canable@can0 --since -2min` shows nothing new).
10. **Unplug the CANable** → `amr.service` stops (`BindsTo`); replug → both come back; drives may show `8130h` and need a power cycle (expected, RUNBOOK §4).
11. **20 min idle** → no screen blanking, no sleep.
12. **Tests**: `python3 tests/run_all.py` = 531 / 531; per-package pytest green.

---

## 10. What lives outside the repo (drift list)

These are the files a `git clone` does **not** give you. Everything in this list
is reproduced above; if any of them changes on the vehicle, update this document.

| Path | Section |
|---|---|
| `/etc/netplan/{50-cloud-init,55-usb-tether,60-rfid-lan1,70-nanoscan3}.yaml` | 2.2 |
| `/etc/NetworkManager/system-connections/agv-net.nmconnection` | 2.3 |
| `/etc/udev/rules.d/70-canable.rules`, `/etc/systemd/system/canable@.service` | 3 |
| `/etc/systemd/system/amr.service` (installed copy of `amr_ws/deploy/amr.service`) | 6 |
| `/etc/systemd/logind.conf.d/{ignore-power-key,50-amr}.conf`; masked sleep targets | 1 |
| `/etc/nginx/sites-available/amr-kiosk`, `/var/www/amr/amr-waiting.html` | 7.3 |
| `/usr/local/bin/{amr-kiosk-session,amr-kiosk-browser,amr-display-hotplug.sh}`, `/usr/share/xsessions/amr-kiosk.desktop` | 7.4 |
| `/etc/chromium/policies/managed/amr-kiosk.json` | 7.5 |
| `/etc/X11/xorg.conf.d/10-amr-noblank.conf` | 7.6 |
| `/etc/lightdm/lightdm.conf.d/50-amr-autologin.conf`, `/etc/systemd/system/lightdm.service.d/override.conf` | 7.7 |
| `~/.bashrc` block, `~/.ssh/authorized_keys` + deploy key | 5.3, 5.1 |
| `~/xfce-kiosk-staging/` (source of the kiosk files, with `README-kiosk.md`, `README-seamless.md`) | 7 |
| `~/amr_maps/` (map bundles = **vehicle data**, back up before a reinstall), `~/.amr/` (logs, evidence, `operations.jsonl`) | 5.1 |
| user-site pip packages (`~/.local/lib/python3.10/site-packages`) | 5.2 |

Recommended next step: move `~/xfce-kiosk-staging/kiosk/` into the repo (for
example `amr_ws/deploy/host/`) with an `install-host.sh` that does sections 1–3
and 7, so a second vehicle is a clone plus two scripts. Until then this file is
the authority.

## 11. Open items found while writing this

- The three `/etc/netplan` files marked RECONSTRUCTED have not been diffed against
  the vehicle (root-only). `sudo cat /etc/netplan/*.yaml` and fold in any difference.
- `50-amr.conf` (logind lid/idle ignores) is staged but not installed on the vehicle; only `ignore-power-key.conf` is.
- `manuals/obsolete/rfid-setup/*.sh` are untracked because `.gitignore` negates
  `manuals/rfid-setup/*.sh` (the old path). Fix the negation or the scripts will be lost.
- The CANable udev rule matches one adapter's serial; a spare adapter needs its own line.
- `sick_safetyscanners2` writes the scanner's channel-0 data-output settings over
  CoLa2 at every start; the *safety* configuration (fields, monitoring cases) is
  Safety Designer only and is not covered here.
