"""Synchronous SSH API for UniFi Etherlighting devices."""

from __future__ import annotations

import base64
import colorsys
import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Any

from .const import (
    CYCLE_PATTERN_ALL,
    CYCLE_PATTERN_KITT,
    CYCLE_PATTERN_OFFSET,
    DEFAULT_CYCLE_BRIGHTNESS,
    DEFAULT_CYCLE_INTERVAL,
    DEFAULT_CYCLE_STEPS,
    DEFAULT_SCANNER_TAIL,
    MODE_COMMANDS,
)

_LOGGER = logging.getLogger(__name__)


class EtherlighterError(Exception):
    """Base error for Etherlighter failures."""


class CannotConnect(EtherlighterError):
    """Raised when the device cannot be reached over SSH."""


class AuthenticationFailed(EtherlighterError):
    """Raised when SSH authentication fails."""


class HostKeyMismatch(EtherlighterError):
    """Raised when the observed SSH host key does not match the stored key."""

    def __init__(self, expected: str, observed: str) -> None:
        super().__init__(
            f"SSH host key mismatch: expected {expected}, observed {observed}"
        )
        self.expected = expected
        self.observed = observed


@dataclass(frozen=True)
class Color:
    """RGB color value."""

    r: int
    g: int
    b: int


@dataclass(frozen=True)
class PortColor:
    """Color value for one switch port."""

    index: int
    color: Color


@dataclass(frozen=True)
class DeviceInfo:
    """Device metadata returned by mca-cli-op."""

    hostname: str = ""
    ip: str = ""
    mac: str = ""
    model: str = ""
    ntp: str = ""
    status: str = ""
    uptime: str = ""
    version: str = ""
    layout: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True)
class ConnectionResult:
    """Result of validating a device connection."""

    info: DeviceInfo
    host_key_fingerprint: str


@dataclass
class AnimationSettings:
    """Mutable animation settings read by the animation thread."""

    pattern: str
    interval_seconds: float
    brightness: int
    steps: int
    scanner_tail: int


def to_range(start: int, end: int, skip: int) -> tuple[int, ...]:
    """Generate a range of integers, inclusive, with a skip value."""

    return tuple(range(start, end + 1, skip))


def layout_for_model(model: str) -> tuple[tuple[int, ...], ...]:
    """Return known port layout for an Etherlighting switch model."""

    layouts = {
        "USW-Pro-Max-24-PoE": (to_range(1, 24, 1),),
        "USW-Pro-Max-48-PoE": (to_range(1, 47, 2), to_range(2, 48, 2)),
        "USW-Pro-Max-16-PoE": (to_range(1, 16, 1),),
        "USW-Pro-Max-48": (to_range(1, 47, 2), to_range(2, 48, 2)),
        "USW-Pro-Max-24": (to_range(1, 24, 1),),
        "USW-Pro-Max-16": (to_range(1, 16, 1),),
    }
    return layouts.get(model, ())


def color_from_hue(hue: float) -> Color:
    """Convert hue in [0, 1] to full-saturation RGB."""

    r, g, b = colorsys.hsv_to_rgb(hue, 1, 1)
    return Color(r=round(r * 255), g=round(g * 255), b=round(b * 255))


def scale_color(color: Color, brightness: int) -> Color:
    """Scale an RGB color by brightness in percent."""

    factor = brightness / 100
    return Color(
        r=round(color.r * factor),
        g=round(color.g * factor),
        b=round(color.b * factor),
    )


def host_key_fingerprint(key: Any) -> str:
    """Return OpenSSH-style SHA256 fingerprint for a Paramiko host key."""

    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


class _TrustOnFirstUsePolicy:
    """Paramiko missing-host-key policy with stored fingerprint verification."""

    def __init__(self, expected_fingerprint: str | None) -> None:
        self.expected_fingerprint = expected_fingerprint
        self.observed_fingerprint: str | None = None

    def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
        """Accept first key or reject changed keys."""

        observed = host_key_fingerprint(key)
        self.observed_fingerprint = observed
        if self.expected_fingerprint and observed != self.expected_fingerprint:
            raise HostKeyMismatch(self.expected_fingerprint, observed)
        client.get_host_keys().add(hostname, key.get_name(), key)


class EtherlighterClient:
    """Blocking SSH client for Etherlighting commands."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        expected_host_key_fingerprint: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.expected_host_key_fingerprint = expected_host_key_fingerprint

        self._ssh: Any | None = None
        self._host_key_fingerprint: str | None = None
        self._lock = threading.Lock()
        self._color_lock = threading.Lock()
        self._last_port_colors: dict[int, Color] = {}
        self._known_ports: list[int] = []
        self._animation_lock = threading.Lock()
        self._animation_stop: threading.Event | None = None
        self._animation_thread: threading.Thread | None = None
        self._animation_settings: AnimationSettings | None = None

    @property
    def host_key_fingerprint(self) -> str | None:
        """Return the observed SSH host key fingerprint."""

        return self._host_key_fingerprint

    def connect(self) -> str:
        """Open the SSH connection and return the observed host key fingerprint."""

        if self._ssh is not None:
            return self._host_key_fingerprint or ""

        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - loaded by HA requirements
            raise CannotConnect("Paramiko is not installed") from exc

        policy = _TrustOnFirstUsePolicy(self.expected_host_key_fingerprint)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(policy)

        try:
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
        except HostKeyMismatch:
            client.close()
            raise
        except paramiko.AuthenticationException as exc:
            client.close()
            raise AuthenticationFailed("SSH authentication failed") from exc
        except (OSError, paramiko.SSHException) as exc:
            client.close()
            raise CannotConnect(f"Unable to connect to {self.host}:{self.port}") from exc

        if policy.observed_fingerprint is None:
            client.close()
            raise CannotConnect("Device did not present an SSH host key")

        self._ssh = client
        self._host_key_fingerprint = policy.observed_fingerprint
        return policy.observed_fingerprint

    def close(self) -> None:
        """Stop animations and close the SSH connection."""

        self.stop_color_cycle()
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None

    def validate_connection(self) -> ConnectionResult:
        """Connect and fetch device info for config flow validation."""

        fingerprint = self.connect()
        return ConnectionResult(info=self.info(), host_key_fingerprint=fingerprint)

    def exec(self, cmd: str) -> str:
        """Execute one shell command on the switch."""

        self.connect()
        if self._ssh is None:
            raise CannotConnect("SSH client is not connected")

        try:
            with self._lock:
                _, stdout, stderr = self._ssh.exec_command(cmd)
                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                status = stdout.channel.recv_exit_status()
        except OSError as exc:
            self._ssh = None
            raise CannotConnect("SSH command failed") from exc

        if status != 0:
            details = err.strip() or out.strip()
            raise EtherlighterError(
                f"Command failed with exit status {status}: {details}"
            )

        return out

    def info(self) -> DeviceInfo:
        """Fetch and parse device metadata."""

        output = self.exec("mca-cli-op info")
        fields: dict[str, str] = {}

        for line in output.splitlines():
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            fields[parts[0].strip()] = parts[1].strip()

        info = DeviceInfo(
            hostname=fields.get("Hostname", ""),
            ip=fields.get("IP Address", ""),
            mac=fields.get("MAC Address", ""),
            model=fields.get("Model", ""),
            ntp=fields.get("NTP", ""),
            status=fields.get("Status", ""),
            uptime=fields.get("Uptime", ""),
            version=fields.get("Version", ""),
            layout=layout_for_model(fields.get("Model", "")),
        )
        with self._color_lock:
            self._known_ports = [port for row in info.layout for port in row]
        return info

    def set_mode(self, mode: str) -> None:
        """Set a predefined Etherlighting mode."""

        self.stop_color_cycle()
        args = MODE_COMMANDS.get(mode)
        if args is None:
            raise EtherlighterError(f"Unsupported mode: {mode}")

        self.set_led_mode(1)
        self.exec(f"echo {' '.join(args)} > /proc/led/led_config")
        with self._color_lock:
            self._last_port_colors.clear()

    def set_led_mode(self, mode: int) -> None:
        """Set the low-level LED mode."""

        self.exec(f"echo {mode} > /proc/led/led_mode")

    def set_static_color(
        self, color: Color, brightness: int = DEFAULT_CYCLE_BRIGHTNESS
    ) -> None:
        """Set all ports to one static RGB color."""

        if not 0 <= brightness <= 100:
            raise EtherlighterError("Brightness must be between 0 and 100")

        self.stop_color_cycle()
        self.set_led_mode(0)
        self._set_all_ports_color(color, brightness)
        self._remember_all_ports_color(color)

    def set_static_rainbow(self, brightness: int = DEFAULT_CYCLE_BRIGHTNESS) -> None:
        """Paint a frozen rainbow: each port gets a different fixed hue."""

        brightness = self._validate_brightness(brightness)
        ports = self._animation_ports()
        if not ports:
            raise EtherlighterError(
                "Cannot paint a static rainbow without a known port layout"
            )

        self.stop_color_cycle()
        self.set_led_mode(0)
        port_colors = [
            PortColor(
                index=port,
                color=scale_color(color_from_hue(offset / len(ports)), brightness),
            )
            for offset, port in enumerate(ports)
        ]
        self._set_port_colors(port_colors, reset_mode=False, force=True)

    def start_color_cycle(
        self,
        pattern: str = CYCLE_PATTERN_ALL,
        interval_seconds: float = DEFAULT_CYCLE_INTERVAL,
        brightness: int = DEFAULT_CYCLE_BRIGHTNESS,
        steps: int = DEFAULT_CYCLE_STEPS,
        scanner_tail: int = DEFAULT_SCANNER_TAIL,
    ) -> None:
        """Start a background color animation."""

        if not 1 <= steps <= 720:
            raise EtherlighterError("Steps must be between 1 and 720")
        if pattern not in {CYCLE_PATTERN_ALL, CYCLE_PATTERN_OFFSET, CYCLE_PATTERN_KITT}:
            raise EtherlighterError("Pattern must be all, offset, or kitt")
        if (
            pattern in {CYCLE_PATTERN_OFFSET, CYCLE_PATTERN_KITT}
            and not self._animation_ports()
        ):
            raise EtherlighterError(
                "Cannot run per-port animation without a known port layout"
            )

        self.stop_color_cycle()
        settings = AnimationSettings(
            pattern=pattern,
            interval_seconds=self._validate_interval(interval_seconds),
            brightness=self._validate_brightness(brightness),
            steps=steps,
            scanner_tail=self._validate_scanner_tail(scanner_tail),
        )

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_color_cycle,
            args=(stop_event,),
            daemon=True,
            name=f"etherlighter-{self.host}-cycle",
        )
        with self._animation_lock:
            self._animation_stop = stop_event
            self._animation_thread = thread
            self._animation_settings = settings
        thread.start()

    def update_color_cycle_settings(
        self,
        interval_seconds: float | None = None,
        brightness: int | None = None,
        scanner_tail: int | None = None,
    ) -> None:
        """Update settings read by the running color animation."""

        with self._animation_lock:
            settings = self._animation_settings
            if settings is None:
                return
            if interval_seconds is not None:
                settings.interval_seconds = self._validate_interval(interval_seconds)
            if brightness is not None:
                settings.brightness = self._validate_brightness(brightness)
            if scanner_tail is not None:
                settings.scanner_tail = self._validate_scanner_tail(scanner_tail)

    def _validate_interval(self, interval_seconds: float) -> float:
        """Validate and return animation interval in seconds."""

        if not 0.05 <= interval_seconds <= 5:
            raise EtherlighterError("Interval must be between 0.05 and 5 seconds")
        return interval_seconds

    def _validate_brightness(self, brightness: int) -> int:
        """Validate and return animation brightness in percent."""

        if not 0 <= brightness <= 100:
            raise EtherlighterError("Brightness must be between 0 and 100")
        return brightness

    def _validate_scanner_tail(self, scanner_tail: int) -> int:
        """Validate and return scanner tail length."""

        if not 1 <= scanner_tail <= 8:
            raise EtherlighterError("Scanner tail must be between 1 and 8")
        return scanner_tail

    def stop_color_cycle(self) -> bool:
        """Stop the current color animation."""

        with self._animation_lock:
            stop_event = self._animation_stop
            thread = self._animation_thread

        if stop_event is None or thread is None or not thread.is_alive():
            with self._animation_lock:
                self._animation_stop = None
                self._animation_thread = None
                self._animation_settings = None
            return False

        stop_event.set()
        if thread is not threading.current_thread():
            thread.join(timeout=2)

        with self._animation_lock:
            if self._animation_thread is thread:
                self._animation_stop = None
                self._animation_thread = None
                self._animation_settings = None

        return True

    def _run_color_cycle(
        self,
        stop_event: threading.Event,
    ) -> None:
        """Run a color animation until stopped."""

        try:
            self.set_led_mode(0)
            step = 0
            while not stop_event.is_set():
                settings = self._animation_settings_snapshot()
                if settings is None:
                    break
                if settings.pattern == CYCLE_PATTERN_OFFSET:
                    self._set_offset_cycle_frame(
                        step,
                        settings.steps,
                        settings.brightness,
                    )
                elif settings.pattern == CYCLE_PATTERN_KITT:
                    self._set_kitt_cycle_frame(
                        step,
                        settings.scanner_tail,
                        settings.brightness,
                    )
                else:
                    color = color_from_hue((step % settings.steps) / settings.steps)
                    self._set_all_ports_color(color, settings.brightness)
                    self._remember_all_ports_color(color)
                step += 1
                stop_event.wait(settings.interval_seconds)
        except Exception:
            _LOGGER.exception("Etherlighter color cycle failed")
            stop_event.set()

    def _animation_settings_snapshot(self) -> AnimationSettings | None:
        """Return a snapshot of animation settings for one frame."""

        with self._animation_lock:
            if self._animation_settings is None:
                return None
            settings = self._animation_settings
            return AnimationSettings(
                pattern=settings.pattern,
                interval_seconds=settings.interval_seconds,
                brightness=settings.brightness,
                steps=settings.steps,
                scanner_tail=settings.scanner_tail,
            )

    def _set_all_ports_color(
        self, color: Color, brightness: int = DEFAULT_CYCLE_BRIGHTNESS
    ) -> None:
        """Set all switch ports to one RGB color."""

        self.exec(
            "echo '%02X %02X %02X %d' > /proc/led/led_all_port_code"
            % (color.r, color.g, color.b, brightness)
        )

    def _set_offset_cycle_frame(
        self,
        step: int,
        steps: int,
        brightness: int = DEFAULT_CYCLE_BRIGHTNESS,
    ) -> None:
        """Set a single offset color-cycle frame across all known ports."""

        ports = self._animation_ports()
        if not ports:
            raise EtherlighterError(
                "Cannot run offset cycle without a known port layout"
            )

        port_colors = [
            PortColor(
                index=port,
                color=scale_color(
                    color_from_hue(
                        ((step + offset * steps / len(ports)) % steps) / steps
                    ),
                    brightness,
                ),
            )
            for offset, port in enumerate(ports)
        ]
        self._set_port_colors(port_colors, reset_mode=False, force=step == 0)

    def _set_kitt_cycle_frame(
        self,
        step: int,
        scanner_tail: int = DEFAULT_SCANNER_TAIL,
        brightness: int = DEFAULT_CYCLE_BRIGHTNESS,
    ) -> None:
        """Set a single KITT scanner frame across all known ports."""

        ports = self._animation_ports()
        if not ports:
            raise EtherlighterError(
                "Cannot run kitt cycle without a known port layout"
            )
        self._set_port_colors(
            self._kitt_port_colors(ports, step, scanner_tail, brightness),
            reset_mode=False,
            force=step == 0,
        )

    def _kitt_port_colors(
        self,
        ports: list[int],
        step: int,
        scanner_tail: int = DEFAULT_SCANNER_TAIL,
        brightness: int = DEFAULT_CYCLE_BRIGHTNESS,
    ) -> list[PortColor]:
        """Return red KITT scanner colors for one frame."""

        scanner_tail = self._validate_scanner_tail(scanner_tail)
        brightness = self._validate_brightness(brightness)
        if len(ports) == 1:
            head_index = 0
            direction = 1
        else:
            period = (len(ports) - 1) * 2
            phase = step % period
            if phase <= len(ports) - 1:
                head_index = phase
                direction = 1
            else:
                head_index = period - phase
                direction = -1

        port_colors: list[PortColor] = []
        for index, port in enumerate(ports):
            distance = (head_index - index) * direction
            if distance < 0 or distance > scanner_tail:
                red = 0
            elif distance == 0:
                red = round(255 * brightness / 100)
            else:
                fade = (scanner_tail - distance + 1) / (scanner_tail + 1)
                red = round(255 * brightness * fade / 100)
            port_colors.append(PortColor(index=port, color=Color(red, 0, 0)))
        return port_colors

    def _set_port_colors(
        self,
        port_colors: list[PortColor],
        reset_mode: bool = True,
        force: bool = False,
    ) -> None:
        """Set specific ports to specific RGB colors."""

        if reset_mode:
            self.set_led_mode(0)

        cmds: list[str] = []
        changed_port_colors: list[PortColor] = []
        with self._color_lock:
            previous_colors = {
                port_color.index: self._last_port_colors.get(port_color.index)
                for port_color in port_colors
            }

        for port_color in port_colors:
            index = port_color.index
            color = port_color.color
            previous = previous_colors.get(index)
            if not force and previous == color:
                continue

            changed_port_colors.append(port_color)
            if force or previous is None or previous.r != color.r:
                cmds.append(f"echo {index} r {color.r * 100} > /proc/led/led_color")
            if force or previous is None or previous.g != color.g:
                cmds.append(f"echo {index} g {color.g * 100} > /proc/led/led_color")
            if force or previous is None or previous.b != color.b:
                cmds.append(f"echo {index} b {color.b * 100} > /proc/led/led_color")

        if cmds:
            self.exec(" && ".join(cmds))
            self._remember_port_colors(changed_port_colors)

    def _animation_ports(self) -> list[int]:
        """Return the best available list of ports for animations."""

        with self._color_lock:
            if self._known_ports:
                return list(self._known_ports)
            return sorted(self._last_port_colors)

    def _remember_all_ports_color(self, color: Color) -> None:
        """Remember current color for all known ports."""

        with self._color_lock:
            if self._known_ports:
                self._last_port_colors = {port: color for port in self._known_ports}

    def _remember_port_colors(self, port_colors: list[PortColor]) -> None:
        """Remember current color for individual ports."""

        with self._color_lock:
            for port_color in port_colors:
                self._last_port_colors[port_color.index] = port_color.color
