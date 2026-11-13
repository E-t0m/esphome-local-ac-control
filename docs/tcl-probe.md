# tcl_probe

Investigation and control of TCL air conditioners through the UART of the Wi-Fi module socket of the indoor unit, from a Linux computer. Two connection types:

- **Adapter** (`-p PORT`): USB UART adapter directly on the Wi-Fi connector of the board
- **Network** (`--url URL`): through the installed ESPHome module with tclac and the package `tcl-protocol.yaml`, without removing anything

## Protocol

- 9600 baud, 8E1 (even parity), 5 V levels; some units use 8N1 (`--parity N`)
- Frame: `BB <response flag> <request flag> <command> <length> … <checksum>`, total length = byte 4 + 6
- Module → unit starts with `BB 00 01`, unit → module with `BB 01 00`
- Commands: `03` set values, `04` query values, `05` set display, `06` acknowledge, `09`/`0A` diagnostics, `0B` set date/time
- Checksum: XOR of all bytes except the last one
- Poll: `BB 00 01 04 02 01 00 BD`
- Control frame: 38 bytes, always contains the **complete** target state
- Status frame: 61, 65 or 68 bytes

Bit assignment after the ESPHome component [tclac](https://github.com/I-am-nightingale/tclac), command set and parity after [AC-hack](https://github.com/adaasch/AC-hack).

Reading with the wrong parity garbles single bytes, typically the frame start `BB 00`. The tool reports such frames as `JUNK`.

## Hardware

- USB UART adapter with 5 V logic (FT232R with VCCIO at 5 V or CH340G at 5 V)
- Connect only GND, TX and RX, TX and RX crossed
- Do **not** connect the 5 V of the board to the adapter
- Determine the pinout with a multimeter, cable colours are not reliable:
	- GND: continuity to the housing or the ground of the board
	- +5V: 5 V against GND
	- TX of the indoor unit: idle level high (about 5 V), flickers during traffic
	- RX of the indoor unit: idle level high, driven by the module

Work on the indoor unit only with the power off (circuit breaker off).

## Setup

```bash
sudo usermod -aG dialout $USER
python3 -m venv ~/venv/tcl
~/venv/tcl/bin/pip install pyserial
ls -l /dev/serial/by-id/
```

## Investigation

### 1. Test without hardware

```bash
python3 tcl_probe.py simulate --link /tmp/ttyTCL
python3 tcl_probe.py -p /tmp/ttyTCL watch
```

### 2. Read along while the original Wi-Fi module is plugged in

Two adapters, common ground, **only RX** connected:

- adapter 1 RX to the TX line of the indoor unit
- adapter 2 RX to the TX line of the module

```bash
python3 tcl_probe.py -p /dev/ttyUSB0=AC -p /dev/ttyUSB1=Module --log capture.jsonl sniff
```

Meanwhile switch through the app. This shows whether the unit speaks the tclac protocol, which status length it delivers and whether the module sends further frame types (handshake, network status).

### 3. Status poll

Unplug the module, connect the adapter in its place (GND, TX, RX):

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 poll --bytes
```

Without a reply: swap TX and RX, check ground, then run the scan.

### 3a. Scan baud rates and protocols

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 --log scan.jsonl scan
```

All baud rates are tried with even and without parity (`--parities E,N`). For each combination the tool first listens passively, then sends a tclac poll, a Tuya heartbeat (`55 AA 00 00 00 00 FF`) and a Tuya product query. Received bytes are printed as hex and classified by frame header:

| Header | Protocol |
|---|---|
| `BB 00 01` | tclac |
| `55 AA` | Tuya MCU, controllable through the ESPHome component `tuya` |
| `AA` | possibly Midea |

### 3b. Loopback test of the adapter

Disconnect the adapter from the unit, connect TX and RX of the adapter directly:

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 scan --bauds 9600
```

Every probe must report `ECHO`. Without the echo the problem lies with the adapter, the port or the permissions.

Check the level of the adapter: measure the idle TX of the adapter against GND. 3.3 V is often not reliable on 5 V inputs.

### 4. Find unknown bytes

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 --log watch.jsonl watch -i 2
```

Switch single functions with the remote control (turbo, sleep, timer, display, vanes, °F). Every change is printed bit by bit, bytes without known meaning are marked `UNKNOWN`.

### 5. Control

Look at the frame first, then send:

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 set --mode cool --temp 22 --fan auto --dry-run
python3 tcl_probe.py -p /dev/ttyUSB0 set --mode cool --temp 22 --fan auto
python3 tcl_probe.py -p /dev/ttyUSB0 set --power off
```

`set` reads the current state first and changes only the given values. A verification poll follows.

According to tclac, `--display off` switches the unit to auto mode.

### 6. Own frames

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 raw "BB 00 01 04 02 01 00 00" --fix-checksum
```

Change unknown bytes in the control frame only one at a time and with care.

## Network mode through the ESPHome module

The package `tcl-protocol.yaml` adds to the ESPHome configuration:

- **UART log:** every byte in the log, `>>>` to the unit, `<<<` from the unit, frames split at pauses of 50 ms
- **Text field "Raw frame":** writes hex bytes unchanged to the UART, without adding a checksum
- **Switch "Status polling":** pauses the cyclic polling of tclac, so that only your own frames run during experiments

Include it under `packages` of the device configuration, then upload via OTA:

```yaml
packages:
  tcl_protocol: !include tcl-protocol.yaml
```

`tcl_probe.py` reads the log through the event stream of the web interface (`/events`) and sends through the text field. Authentication uses digest or basic, user `admin` (`--user`), password through `--password` or the environment variable `TCL_WEB_PASS`:

```bash
export TCL_WEB_PASS='…'
python3 tcl_probe.py --url http://klimatcl.local sniff
python3 tcl_probe.py --url http://klimatcl.local poll --bytes
python3 tcl_probe.py --url http://klimatcl.local --log watch.jsonl watch -i 5
python3 tcl_probe.py --url http://klimatcl.local set --temp 23 --dry-run
python3 tcl_probe.py --url http://klimatcl.local raw "BB 00 01 04 02 01 00 00" --fix-checksum
```

- `sniff` shows both directions: `[Module]` are the frames of tclac and your own, `[AC]` the replies of the unit.
- `poll`, `watch`, `set` and `raw` work as with an adapter. The default waiting times are longer (6 s and 3 s), because the path runs through Wi-Fi and the log.
- `scan` and `simulate` only exist with an adapter.
- While tclac runs, its polls arrive every 5 s as well. For undisturbed experiments switch off "Status polling" in the web interface and on again afterwards.
- `set` and `raw` bypass tclac. The unit takes the values, tclac shows them after its next status poll. A later command from the web interface sends the complete state from tclac again.

## Subcommands

| Command | Purpose |
|---|---|
| `sniff` | read passively, several ports, decode frames |
| `poll` | query the status once, `--bytes` shows every byte |
| `watch` | poll cyclically, changed bytes bit by bit |
| `set` | change the state |
| `raw` | send an arbitrary frame |
| `scan` | try baud rates and protocols (tclac, Tuya), only with an adapter |
| `simulate` | virtual indoor unit on a pseudo terminal, only with an adapter |

`--parity E|N|O` sets the parity for all subcommands except `scan`, default `E`.

`--log FILE` writes all frames as JSON Lines with timestamp, source and decoded values.
