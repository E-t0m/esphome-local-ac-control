# First flash of a TCL Wi-Fi module over the serial port

The TCL units carry the Tuya module TYWE1S (ESP8266EX, 2 MB flash) on the carrier board TYJW2. The original Tuya firmware accepts no foreign firmware over the air, so ESPHome goes onto the module once through the serial port. All later updates run over the air.

## What is needed

- USB UART adapter with **3.3 V logic** (CP2102, CH340, FT232R with VCCIO at 3.3 V). 5 V logic damages the ESP8266.
- Pins or test clips on the pads `U0TX`, `U0RX` and `GND` of the TYWE1S (module pins 8, 11 and 5); on the TYJW2 they are usually led out to a small programming header.
- A 5 V supply for the module, see below.
- ESPHome in a virtual environment, as in the README; it includes `esptool`.

Access to the serial port needs the group `dialout`, once:

```bash
sudo usermod -aG dialout $USER
```

Log out and in again afterwards. The adapter shows up as `/dev/ttyUSB0` or `/dev/ttyACM0`:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

## Wiring

Take the module out of the indoor unit; work on the unit only with the power off (circuit breaker off).

| Adapter | TYWE1S / TYJW2 |
|---|---|
| GND | GND |
| TX | U0RX (pin 11) |
| RX | U0TX (pin 8) |

TX and RX are crossed. The air conditioner connector of the TYJW2 is wired to the alternative UART pins (GPIO13/GPIO15), not to `U0TX`/`U0RX`, so it does not disturb the flashing.

Power: the TYJW2 runs from 5 V through its connector to the indoor unit and has its own 3.3 V regulator. Feed 5 V and GND from the adapter (or another 5 V supply) into these two pins of the connector; determine them with a multimeter as described in [tcl-probe.md, Hardware](tcl-probe.md#hardware), cable colours are not reliable. The 3.3 V pin of most adapters cannot deliver the current peaks of the ESP8266 and leads to aborted transfers.

Alternatively the module stays connected to the indoor unit and is powered from it; then only GND, TX and RX go to the adapter.

## Flash mode

The button on the TYJW2 pulls GPIO0 to GND. The module starts in flash mode when the button is held while the power is switched on:

1. Disconnect the 5 V supply.
2. Hold the button.
3. Connect the 5 V supply.
4. Release the button after about one second.

The module stays in flash mode until the next power cycle. Repeat these steps before every `esptool` or `esphome` command below.

## Back up the original firmware

```bash
~/venv/esphome/bin/esptool --port /dev/ttyUSB0 --baud 115200 read-flash 0 0x200000 tywe1s-original-1.bin
```

Flash mode again, a second time, then compare:

```bash
~/venv/esphome/bin/esptool --port /dev/ttyUSB0 --baud 115200 read-flash 0 0x200000 tywe1s-original-2.bin
cmp tywe1s-original-1.bin tywe1s-original-2.bin && echo identical
```

Only two identical reads are a valid backup. The image contains the Wi-Fi credentials and the Tuya device keys of the module: keep it private, never publish it, and do not commit it.

## Erase the flash

```bash
~/venv/esphome/bin/esptool --port /dev/ttyUSB0 erase-flash
```

This removes the Tuya firmware, its keys and its stored data, so ESPHome starts with empty settings.

## Flash ESPHome

Prepare the configuration as described in the README (`secrets.yaml`, `build-ui.py`), then, in flash mode:

```bash
~/venv/esphome/bin/esphome run klima-tcl.yaml --device /dev/ttyUSB0
```

If the transfer aborts, flash with a lower speed:

```bash
~/venv/esphome/bin/esphome run klima-tcl.yaml --device /dev/ttyUSB0 --upload_speed 115200
```

The serial flash writes the layout `eagle.flash.2m64.ld` directly; the transition firmware `klima-tcl-transition.yaml` is only needed for modules that already run ESPHome with the default layout.

After the upload the module needs a power cycle without the button. It connects to the Wi-Fi from `secrets.yaml`; if that fails it opens the hotspot "klimatcl Fallback Hotspot" with the password `tcl_recovery_pass`.

## Install and test

1. Remove the adapter, put the module back into the indoor unit and connect it.
2. Switch the power on.
3. Open `http://klimatcl.local` (user `admin`, password `tcl_web_pass`). The climate entity shows the current temperature as soon as the module talks to the unit.

All further updates run over the air:

```bash
~/venv/esphome/bin/esphome run klima-tcl.yaml --device klimatcl.local
```

## Restore the original firmware

In flash mode:

```bash
~/venv/esphome/bin/esptool --port /dev/ttyUSB0 --baud 115200 write-flash 0 tywe1s-original-1.bin
```
