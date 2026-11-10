# esphome-local-ac-control

ESPHome firmware for TCL and Midea air conditioners (e.g. Bosch Climate 4000i) that runs with or without Home Assistant: control through the built-in web interface and its REST API, schedules and a self-learning setpoint guidance on the device, a web interface that works without internet access. Home Assistant connects through the native API as usual.

<p>
	<a href="docs/bosch-midea.png"><img src="docs/bosch-midea.png" width="400" alt="Web interface of a Bosch Climate 4000i (Midea)"></a>
	<a href="docs/tcl-euromate.png"><img src="docs/tcl-euromate.png" width="400" alt="Web interface of a TCL unit"></a>
</p>

Example configurations:

| Configuration | Tested with | Module |
|---|---|---|
| `klima-tcl.yaml` | TCL TAC-09CHSD/XA71I (2.6 kW) and the identical Euromate 482255 | Tuya TYWE1S (ESP8266, 2 MB) on carrier board TYJW2 |
| `klima-bosch.yaml` | Bosch Climate 4000i (Midea platform) | SMLIGHT SLWF-01Pro v2 |

For several units of the same type, copy the example, change `device_name` (TCL) or `name` (Bosch), `humanly_name` / `friendly_name` and the secret names.

TCL units use the component [tclac](https://github.com/I-am-nightingale/tclac), Midea units the component [juchong/esphome-midea](https://github.com/juchong/esphome-midea).

## Files

| File | Purpose |
|---|---|
| `schedule.yaml`, `schedule.h` | schedules as a text field, time via NTP |
| `setpoint-guidance.yaml` | self-learning setpoint guidance for heating |
| `standalone.yaml` | select "Reboot without API client", button "Reboot" |
| `tcl-extra.yaml` | additional values from the TCL status frames (compressor frequency, estimated power, timers, energy, unknown bytes) |
| `tcl-protocol.yaml` | raw UART access for `tcl_probe.py` |
| `history.yaml`, `history.h` | history in RAM with growing interval (1 s up to 64 s, about 10.7 hours), shown as a chart in the web interface |
| `ui-extras.js` | extras for the web interface: collapsible log, adjustable column width, lock while offline |
| `build-ui.py` | builds `esphome-ui.js`: web interface with icons and `ui-extras.js`, served from the device |
| `klima-tcl-transition.yaml` | transition firmware that switches the flash layout of a TYWE1S via OTA |
| `tcl_probe.py` | investigate and control TCL units through the UART, by adapter or through the ESPHome module |
| `secrets.example.yaml` | template for `secrets.yaml` |

## Setup

```bash
python3 -m venv ~/venv/esphome
~/venv/esphome/bin/pip install esphome
cp secrets.example.yaml secrets.yaml
```

Fill in `secrets.yaml`. Quote every value, otherwise YAML may read a numeric password as a number. Keys and passwords:

```bash
openssl rand -base64 32
openssl rand -hex 12
```

Build the web interface, then compile and upload:

```bash
~/venv/esphome/bin/python build-ui.py klima-tcl.yaml klima-bosch.yaml
~/venv/esphome/bin/esphome run klima-bosch.yaml --device IP-OF-THE-MODULE
```

`build-ui.py` must run again after every ESPHome update and after adding icons to a configuration. On the first run it downloads the Iconify icon set "mdi" once (`.mdi.json`); afterwards no internet access is needed.

## Web interface without internet

ESPHome's web interface (version 3) loads its program and its icons from the internet. `build-ui.py` takes the interface of the installed ESPHome version, adds every icon used by the interface and by the configurations as `IconifyPreload`, appends `ui-extras.js` and writes `esphome-ui.js`. The configurations embed it with:

```yaml
web_server:
  version: 3
  js_url: ""
  js_include: esphome-ui.js
```

`ui-extras.js` adds:

- a log icon at the top right that shows or hides the log column; collapsed by default
- a draggable divider to the right of the entities, double click resets the width
- all controls locked while the interface has no connection to the device
- the device name at the top reloads the page when clicked, e.g. after an update
- with `history.yaml` on the device, a history chart above the entities (see below); it fills the width and compresses as the history grows

The browser remembers these settings per device.

## Schedules

The text field "Schedule" holds any number of rules, separated by `;`:

```
xxxxx__ 6:30 22 heat auto v3; xxxxx__ 8:00 off; _____xx 8:20 21 keep 2
```

| Part | Required | Values |
|---|---|---|
| days | yes | 7 characters Mon…Sun, `x` = on, `_` = off |
| time | yes | `6:30`, `06:30`, `20:05` |
| temperature | no | e.g. `22` or `21.5`, before the mode; missing = unchanged |
| mode | yes | `off`, `on` (last used mode), `auto`, `heat`, `cool`, `dry`, `fan`, `keep` (mode and on/off unchanged) |
| fan | no | first word after the mode, an option of the device's select "Fan speed" |
| vanes | no | `v1`–`v5` vertical (`v1` = fully up), `h1`–`h5` horizontal (`h1` = fully left) |

- Each rule switches once at its minute. With several rules at the same minute the last one wins.
- With `keep` and the unit switched off only the target temperature is set.
- After a reboot the last switching point of the past 15 minutes is caught up, unless it was executed before the reboot.
- "Schedule check" shows `OK, n rules` or the first error, "Schedule syntax" a short guide with the fan words of the device, "Next switching" the next switching point with all its settings.
- The switch "Schedules" turns all schedules on or off.
- At most 10 rules. They are stored packed rather than as text, because the settings storage of the ESP8266 holds only 512 bytes for all stored settings. After a reboot the text field shows the stored rules in the same format; rules with errors are not stored.

The time comes from NTP. The configurations here use the router (`ntp_server: fritz.box`), so no internet access is needed while the router keeps its own clock.

## Setpoint guidance

Inverter units stop the compressor in heating mode once the room is warm enough. During these idle phases some units move the vanes to a rest position and blow little air. The setpoint guidance keeps the compressor at a low stage instead:

- **Learning:** at every compressor stop in heating mode the device records how far the room temperature was above the setpoint, likewise at every restart. Each becomes a moving average that survives reboots.
- **Guiding:** once enough stops are known and "Setpoint guidance" is on, the setpoint follows the room temperature just above the learned stop threshold, between "Comfort temperature" and "Comfort temperature" minus "Guidance max reduction".
- Below the comfort temperature, after a stop and above "Guidance overheat limit" the comfort temperature is used as setpoint.
- A setpoint changed by hand becomes the new comfort temperature. With guidance on, schedule temperatures set the comfort temperature.

All parameters are set in the web interface:

| Entity | Default | Meaning |
|---|---|---|
| Guidance safety margin | 0.5 °C | distance to the learned stop threshold |
| Guidance overheat limit | 1.0 °C | above comfort + limit an idle phase is allowed |
| Guidance max reduction | 4 °C | lowest setpoint = comfort − reduction |
| Guidance min interval | 3 min | minimum time between two reductions |
| Guidance learning weight | 0.3 | weight of a new measurement in the average |
| Guidance samples needed | 3 | stops before guidance acts |

"Guidance status" and "Guidance learned" show what the guidance does and has learned; learning runs while guidance is off as well. The compressor state comes from the compressor frequency of the Midea component or from the sensor "Compressor frequency" of `tcl-extra.yaml` (TCL, byte 39 of the status frame). TCL units accept the setpoint in whole degrees only.

## TCL: compressor frequency and estimated power

Byte 39 of the TCL status frame is the compressor frequency in Hz (0 = compressor stopped). `tcl-extra.yaml` shows it as "Compressor frequency" and, for comparison, as hex and decimal in "Compressor byte 39".

"Estimated power" calculates the electrical power of the whole unit from it:

| Frequency | Power |
|---|---|
| 0 Hz | "Power idle" |
| above 0 Hz | "Power offset" + "Power per Hz" × frequency |

The defaults (29 W, −50 W, 18.3 W/Hz) were measured on the Euromate 482255 (TCL TAC-09CHSD/XA71I) in heating mode with fan auto; they match the rating plate (heating 240–1552 W, 699 W rated), whose minimum of 240 W corresponds to about 16 Hz; single values deviate by about ±15 % depending on temperatures. The three values can be adjusted in the web interface. "Estimated energy" sums up the energy since the last boot.

## History

`history.yaml` keeps 600 samples (about 3.6 KB) in the RAM of the module, with a growing interval: it starts with one sample per second; whenever the buffer is full, neighbouring samples are averaged in pairs and the interval doubles, up to 64 s, which covers about 10.7 hours. Recorded values: compressor frequency, room temperature, setpoint (empty while the unit is off) and power (estimated power on the TCL units, total power on the Midea unit). The device serves it as `/history.json`; `ui-extras.js` shows it as three charts above the entities, so the curves are complete when the page is opened. The history starts empty after every reboot; writing it to flash would wear the flash out.

## Midea: Bosch Climate 4000i

`klima-bosch.yaml` is written for the Bosch Climate 4000i and works for other units of the Midea platform as well. The SLWF-01Pro v2 plugs into the unit with its USB-A plug and talks to it through the UART on GPIO12/GPIO14.

| Entity | Meaning |
|---|---|
| Climate | mode, setpoint (0.5 °C steps); Heat/Cool, Heat, Cool, Dry and Fan only are always offered, because the autoconf report of the 4000i does not always contain heating |
| Fan speed | select Auto, Low, Medium, High, Silent, Turbo (Silent and Turbo only if the unit reports them), since the climate card of the web interface shows no fan modes |
| Vertical louver, Horizontal louver | fixed vane position in five steps or "Last position"; the position is moved to again every time the unit is switched on, and the position reported by the unit is shown in the select |
| Swing step | moves the vanes one step, like a short press of the swing button |
| Beeper, Toggle display | beeper on/off, display of the indoor unit on/off |
| Compressor frequency, Outdoor unit power | from the diagnostic data of the unit |
| Indoor fan speed, Indoor fan target speed, Outdoor fan speed | fan speeds in rpm, so the current stage is visible in fan mode auto |
| Outdoor temperature, Room temperature | values reported by the unit |
| Total power, Total energy | estimated power of the whole unit, see below |

The vanes are set through the Midea properties 0x0009 (vertical) and 0x000A (horizontal) with command B0 and the values 1, 25, 50, 75, 100, like msmart does; property 0x001A (buzzer) is sent along and follows the switch "Beeper", otherwise the unit beeps.

The diagnostic values come from several data groups that the component queries in turn, one per `diagnostic_interval`. With 2 s each group is refreshed about every 10 s.

Schedules, setpoint guidance and history work as on the TCL units; the setpoint guidance uses 0.5 °C steps and the compressor frequency reported by the unit.

## Midea: total power

The Bosch Climate 4000i reports "Outdoor unit power", which covers only part of the consumption. `klima-bosch.yaml` estimates the power of the whole unit from it as "Total power":

| Compressor | Power |
|---|---|
| stopped | "Power idle" |
| running | "Power offset" + "Power factor" × outdoor unit power |

The defaults (12 W, 66 W, 1.13) were measured on this unit with fan auto and match a power meter within about 10 W at steady load. "Total energy" sums up the energy since the last boot.

## Running without Home Assistant

ESPHome reboots a device after 15 minutes without an API client. `standalone.yaml` replaces this with the select "Reboot without API client" (`Never`, `15 min` … `24 h`, default `Never`). A pending switching point postpones the reboot until it has been executed.

On the ESP8266, the diagnostic value "Settings storage" shows how much of the 128 words (512 bytes) for stored settings is in use. Settings that no longer fit are silently not stored, so it should stay below 128.

Control through REST, with digest authentication:

```bash
curl --digest -u admin:PASSWORD -X POST "http://klima-bosch.local/climate/Climate/set?mode=HEAT&target_temperature=23"
curl --digest -u admin:PASSWORD -X POST "http://klima-bosch.local/select/Fan%20speed/set?option=High"
curl --digest -u admin:PASSWORD -X POST "http://klima-bosch.local/text/Schedule/set?value=xxxxx__%206:30%20heat"
```

On the TCL units the climate entity is called `<device_name> Climate`, e.g. `/climate/klimatcl%20Climate/set`.

In a crontab every `%` must be written as `\%`.

## Flash layout of the TYWE1S

The TYWE1S has 2 MB flash. With the default layout only about 400 KB remain for an OTA update next to a firmware of this size. The TCL configurations use the layout `eagle.flash.2m64.ld` (64 KB file system, unused by ESPHome), which leaves almost 1 MB.

A module still running the default layout is switched in two OTA steps:

```bash
~/venv/esphome/bin/esphome compile klima-tcl-transition.yaml
grep ldscript .esphome/build/klimatcl/platformio.ini
~/venv/esphome/bin/esphome upload klima-tcl-transition.yaml --device IP
~/venv/esphome/bin/esphome run klima-tcl.yaml --device IP
```

The transition firmware only contains Wi-Fi and update and fits into the small free space. The stored settings of the device are empty once afterwards, because their flash sector moves with the layout.

## tcl_probe

Investigation and control of TCL air conditioners through the UART of the Wi-Fi module socket of the indoor unit, from a Linux computer. Two connection types:

- **Adapter** (`-p PORT`): USB UART adapter directly on the Wi-Fi connector of the board
- **Network** (`--url URL`): through the installed ESPHome module with tclac and the package `tcl-protocol.yaml`, without removing anything

### Protocol

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

### Hardware

- USB UART adapter with 5 V logic (FT232R with VCCIO at 5 V or CH340G at 5 V)
- Connect only GND, TX and RX, TX and RX crossed
- Do **not** connect the 5 V of the board to the adapter
- Determine the pinout with a multimeter, cable colours are not reliable:
	- GND: continuity to the housing or the ground of the board
	- +5V: 5 V against GND
	- TX of the indoor unit: idle level high (about 5 V), flickers during traffic
	- RX of the indoor unit: idle level high, driven by the module

Work on the indoor unit only with the power off (circuit breaker off).

### Setup

```bash
sudo usermod -aG dialout $USER
python3 -m venv ~/venv/tcl
~/venv/tcl/bin/pip install pyserial
ls -l /dev/serial/by-id/
```

### Investigation

#### 1. Test without hardware

```bash
python3 tcl_probe.py simulate --link /tmp/ttyTCL
python3 tcl_probe.py -p /tmp/ttyTCL watch
```

#### 2. Read along while the original Wi-Fi module is plugged in

Two adapters, common ground, **only RX** connected:

- adapter 1 RX to the TX line of the indoor unit
- adapter 2 RX to the TX line of the module

```bash
python3 tcl_probe.py -p /dev/ttyUSB0=AC -p /dev/ttyUSB1=Module --log capture.jsonl sniff
```

Meanwhile switch through the app. This shows whether the unit speaks the tclac protocol, which status length it delivers and whether the module sends further frame types (handshake, network status).

#### 3. Status poll

Unplug the module, connect the adapter in its place (GND, TX, RX):

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 poll --bytes
```

Without a reply: swap TX and RX, check ground, then run the scan.

#### 3a. Scan baud rates and protocols

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 --log scan.jsonl scan
```

All baud rates are tried with even and without parity (`--parities E,N`). For each combination the tool first listens passively, then sends a tclac poll, a Tuya heartbeat (`55 AA 00 00 00 00 FF`) and a Tuya product query. Received bytes are printed as hex and classified by frame header:

| Header | Protocol |
|---|---|
| `BB 00 01` | tclac |
| `55 AA` | Tuya MCU, controllable through the ESPHome component `tuya` |
| `AA` | possibly Midea |

#### 3b. Loopback test of the adapter

Disconnect the adapter from the unit, connect TX and RX of the adapter directly:

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 scan --bauds 9600
```

Every probe must report `ECHO`. Without the echo the problem lies with the adapter, the port or the permissions.

Check the level of the adapter: measure the idle TX of the adapter against GND. 3.3 V is often not reliable on 5 V inputs.

#### 4. Find unknown bytes

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 --log watch.jsonl watch -i 2
```

Switch single functions with the remote control (turbo, sleep, timer, display, vanes, °F). Every change is printed bit by bit, bytes without known meaning are marked `UNKNOWN`.

#### 5. Control

Look at the frame first, then send:

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 set --mode cool --temp 22 --fan auto --dry-run
python3 tcl_probe.py -p /dev/ttyUSB0 set --mode cool --temp 22 --fan auto
python3 tcl_probe.py -p /dev/ttyUSB0 set --power off
```

`set` reads the current state first and changes only the given values. A verification poll follows.

According to tclac, `--display off` switches the unit to auto mode.

#### 6. Own frames

```bash
python3 tcl_probe.py -p /dev/ttyUSB0 raw "BB 00 01 04 02 01 00 00" --fix-checksum
```

Change unknown bytes in the control frame only one at a time and with care.

### Network mode through the ESPHome module

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

### Subcommands

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

## License

MIT, see `LICENSE`. The components tclac and juchong/esphome-midea are included from their own repositories and keep their own licenses.
