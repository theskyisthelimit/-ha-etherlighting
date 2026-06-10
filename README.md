# Etherlighter

<p align="center">
  <img src="custom_components/etherlighter/brand/logo.png" alt="Etherlighter logo" width="180">
</p>

<p align="center">
  <strong>Home Assistant control for UniFi Etherlighting switch LEDs.</strong>
</p>

<p align="center">
  <a href="https://www.hacs.xyz/"><img alt="HACS custom" src="https://img.shields.io/badge/HACS-Custom-41BDF5?logo=homeassistant"></a>
  <a href="https://www.home-assistant.io/"><img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-18BCF2?logo=homeassistant"></a>
  <img alt="Local push" src="https://img.shields.io/badge/IoT-Local%20SSH-00A0DC">
</p>

Etherlighter is a custom Home Assistant integration for UniFi switches with
Etherlighting LEDs. It lets you switch between the built-in UniFi LED modes,
set a static all-port RGB color, and run custom effects such as a static
per-port rainbow and color cycles directly from the Home Assistant UI or from
automations.

This project is independent, unofficial, and not affiliated with Ubiquiti.

## Features

- Home Assistant config flow with SSH host, port, username, and password.
- Device entry with model, hostname, MAC address, and firmware metadata when
  available from the switch.
- **Mode** select for the built-in UniFi LED behaviors (firmware-driven): the
  status indicators `Network`, `Speed`, `PoE`, `Device Type`, plus `Cold Reset`
  (rainbow), `Warm Reset` (breathing), `Boot Done`, `Port Locate`, and
  `Port Locate Unset`.
- **Animation** select for the decorative effects this integration renders:
  `Off`, `Static Rainbow` (a frozen per-port rainbow), `Cycle All`, and
  `Cycle Staggered`.
- RGB light entity for setting one static color on all ports.
- `Breathing Effect` switch to toggle the built-in white breathing animation
  (the warm-reset effect) on and off.
- Number controls for transition speed and animation brightness.
- `Stop Cycle` button to stop the active animation in one tap.
- Home Assistant actions for scripts, scenes, dashboards, and automations.
- Trust-on-first-use SSH host-key handling to avoid silently connecting to a
  changed host key.

> **Mode vs. Animation:** *Mode* selects a built-in UniFi behavior that runs on
> the switch firmware — the functional status indicators as well as the native
> reset animations (cold reset = rainbow, warm reset = breathing). *Animation*
> is a decorative effect this integration paints over SSH. Picking one clears
> the other.
>
> The `KITT Scanner` is implemented but disabled in the UI for now: it is driven
> frame-by-frame over SSH and stutters on the switch CPU. It can be re-enabled
> later (the smooth, firmware-native animations live under *Mode*).

## Supported Devices

The integration targets UniFi Professional Max switches with Etherlighting.
Known port layouts are included for:

- `USW-Pro-Max-16`
- `USW-Pro-Max-16-PoE`
- `USW-Pro-Max-24`
- `USW-Pro-Max-24-PoE`
- `USW-Pro-Max-48`
- `USW-Pro-Max-48-PoE`

Built-in modes may work on additional Etherlighting devices, but per-port
animations need a known port layout. If your model is missing, open an issue
with the model string from Home Assistant and the physical port layout.

## HACS Installation

1. Open HACS in Home Assistant.
2. Go to `Integrations`.
3. Open the three-dot menu and choose `Custom repositories`.
4. Add this repository URL:

   ```text
   https://github.com/theskyisthelimit/-ha-etherlighting
   ```

5. Set the category to `Integration`.
6. Install `Etherlighter`.
7. Restart Home Assistant.
8. Go to `Settings` > `Devices & services` > `Add integration`.
9. Search for `Etherlighter`.
10. Enter the SSH details for your UniFi switch.

You can find UniFi device SSH credentials in UniFi Network under
`Settings` > `System` > `Advanced` > `Device SSH Authentication`.

## Home Assistant Entities

After setup, Etherlighter creates entities similar to:

| Entity type | Purpose |
| --- | --- |
| `select.etherlighter_mode` | Pick a built-in UniFi LED mode (status indicators plus the native cold/warm reset animations). |
| `select.etherlighter_animation` | Pick a decorative effect (`Off`, `Static Rainbow`, `Cycle All`, `Cycle Staggered`). |
| `switch.etherlighter_breathing_effect` | Toggle the built-in white breathing effect (warm reset). |
| `light.etherlighter_all_ports` | Set one static RGB color on all ports. |
| `number.etherlighter_transition_speed` | Adjust animation speed from 1 to 100. |
| `number.etherlighter_animation_brightness` | Adjust animation brightness from 0 to 100 percent. |
| `button.etherlighter_stop_cycle` | Stop the active animation. |

Entity IDs can differ depending on your Home Assistant naming choices.

## Actions

Etherlighter exposes three Home Assistant actions.

### Set Mode

```yaml
action: etherlighter.set_mode
target:
  entity_id: select.etherlighter_mode
data:
  mode: network
```

### Start Animation

```yaml
action: etherlighter.start_cycle
target:
  entity_id: select.etherlighter_animation
data:
  pattern: offset
  interval: 0.2
  brightness: 100
```

Supported `pattern` values:

- `all`
- `offset`

### Stop Animation

```yaml
action: etherlighter.stop_cycle
target:
  entity_id: select.etherlighter_animation
```

## Example Automations

Run an attention-grabbing staggered color cycle when Home Assistant enters
alarm mode:

```yaml
alias: Etherlighter alarm cycle
triggers:
  - trigger: state
    entity_id: alarm_control_panel.home
    to: armed_away
actions:
  - action: etherlighter.start_cycle
    target:
      entity_id: select.etherlighter_animation
    data:
      pattern: offset
      interval: 0.12
      brightness: 100
```

Restore normal network LEDs at night:

```yaml
alias: Etherlighter restore network mode
triggers:
  - trigger: time
    at: "23:00:00"
actions:
  - action: etherlighter.set_mode
    target:
      entity_id: select.etherlighter_mode
    data:
      mode: network
```

## How It Works

Etherlighter connects to the switch over SSH and runs commands that adjust the
Etherlighting LED engine on the device. Some operations use reverse-engineered
LED controls under `/proc/led/*`.

The Home Assistant integration keeps blocking SSH work out of the event loop by
running device calls in Home Assistant's executor. Animations run in a dedicated
worker thread and are stopped cleanly when you change modes, stop an animation,
or unload the config entry.

## Safety Notes

This integration uses SSH and private device internals. That can break after
firmware updates and may be outside the normal supported operation of your
UniFi device.

Use it at your own risk. The author is not responsible for device issues,
configuration loss, support problems, or warranty impact caused by using this
software.

## Local Debug App

This repository also contains a standalone local web app (`etherlighter.py`) for
debugging directly against a switch without Home Assistant. It exposes per-port
colors, the predefined modes, a `Static Rainbow`, and the `Cycle All`,
`Cycle Staggered`, and `KITT Scanner` effects with live sliders for transition
speed, animation brightness, and KITT scanner tail. The KITT scanner is kept
here (unlike the integration UI) precisely because it is useful for debugging.
The HACS integration does not need this local web server at runtime.

```sh
python3 -m pip install -r requirements.txt
python3 etherlighter.py --device <ip> --user <username> --password '<password>'
```

Then open `http://localhost:8080`.

## Credits

Etherlighter is based on
[`robherley/etherlighter`](https://github.com/robherley/etherlighter), the
original standalone local app that this Home Assistant integration grew out of,
and was inspired by
[`adamjezek98/ubnt-etherlighting`](https://github.com/adamjezek98/ubnt-etherlighting).
Thanks for the original reverse-engineering work and the idea.

This README uses project-owned generated branding instead of third-party product
or inspiration-project screenshots.

## Keywords

Home Assistant, HACS, UniFi, Ubiquiti, Etherlighting, Professional Max,
USW-Pro-Max, switch LEDs, network switch LED automation, KITT scanner,
Knight Rider style LED animation.
