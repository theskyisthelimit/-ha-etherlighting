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
    CYCLE_PATTERN_OFFSET,
    DEFAULT_CYCLE_BRIGHTNESS,
    DEFAULT_CYCLE_INTERVAL,
    DEFAULT_CYCLE_STEPS,
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
        self._animation_pattern: str | None = None

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

    def start_color_cycle(
        self,
        pattern: str = CYCLE_PATTERN_ALL,
        interval_seconds: float = DEFAULT_CYCLE_INTERVAL,
        brightness: int = DEFAULT_CYCLE_BRIGHTNESS,
        steps: int = DEFAULT_CYCLE_STEPS,
    ) -> None:
        """Start a background color animation."""

        if not 0.05 <= interval_seconds <= 5:
            raise EtherlighterError("Interval must be between 0.05 and 5 seconds")
        if not 0 <= brightness <= 100:
            raise EtherlighterError("Brightness must be between 0 and 100")
        if not 1 <= steps <= 720:
            raise EtherlighterError("Steps must be between 1 and 720")
        if pattern not in {CYCLE_PATTERN_ALL, CYCLE_PATTERN_OFFSET}:
            raise EtherlighterError("Pattern must be either all or offset")
        if pattern == CYCLE_PATTERN_OFFSET and not self._animation_ports():
            raise EtherlighterError("Cannot run offset cycle without a known port layout")

        self.stop_color_cycle()

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_color_cycle,
            args=(stop_event, pattern, interval_seconds, brightness, steps),
            daemon=True,
            name=f"etherlighter-{self.host}-cycle",
        )
        with self._animation_lock:
            self._animation_stop = stop_event
            self._animation_thread = thread
            self._animation_pattern = pattern
        thread.start()

    def stop_color_cycle(self) -> bool:
        """Stop the current color animation."""

        with self._animation_lock:
            stop_event = self._animation_stop
            thread = self._animation_thread

        if stop_event is None or thread is None or not thread.is_alive():
            with self._animation_lock:
                self._animation_stop = None
                self._animation_thread = None
                self._animation_pattern = None
            return False

        stop_event.set()
        if thread is not threading.current_thread():
            thread.join(timeout=2)

        with self._animation_lock:
            if self._animation_thread is thread:
                self._animation_stop = None
                self._animation_thread = None
                self._animation_pattern = None

        return True

    def _run_color_cycle(
        self,
        stop_event: threading.Event,
        pattern: str,
        interval_seconds: float,
        brightness: int,
        steps: int,
    ) -> None:
        """Run a color animation until stopped."""

        try:
            self.set_led_mode(0)
            step = 0
            while not stop_event.is_set():
                if pattern == CYCLE_PATTERN_OFFSET:
                    self._set_offset_cycle_frame(step, steps)
                else:
                    color = color_from_hue((step % steps) / steps)
                    self._set_all_ports_color(color, brightness)
                    self._remember_all_ports_color(color)
                step += 1
                stop_event.wait(interval_seconds)
        except Exception:
            _LOGGER.exception("Etherlighter color cycle failed")
            stop_event.set()

    def _set_all_ports_color(
        self, color: Color, brightness: int = DEFAULT_CYCLE_BRIGHTNESS
    ) -> None:
        """Set all switch ports to one RGB color."""

        self.exec(
            "echo '%02X %02X %02X %d' > /proc/led/led_all_port_code"
            % (color.r, color.g, color.b, brightness)
        )

    def _set_offset_cycle_frame(self, step: int, steps: int) -> None:
        """Set a single offset color-cycle frame across all known ports."""

        ports = self._animation_ports()
        if not ports:
            raise EtherlighterError("Cannot run offset cycle without a known port layout")

        port_colors = [
            PortColor(
                index=port,
                color=color_from_hue(((step + offset * steps / len(ports)) % steps) / steps),
            )
            for offset, port in enumerate(ports)
        ]
        self._set_port_colors(port_colors, reset_mode=False)

    def _set_port_colors(
        self, port_colors: list[PortColor], reset_mode: bool = True
    ) -> None:
        """Set specific ports to specific RGB colors."""

        if reset_mode:
            self.set_led_mode(0)

        cmds: list[str] = []
        for port_color in port_colors:
            index = port_color.index
            color = port_color.color
            cmds.extend(
                [
                    f"echo {index} r {color.r * 100} > /proc/led/led_color",
                    f"echo {index} g {color.g * 100} > /proc/led/led_color",
                    f"echo {index} b {color.b * 100} > /proc/led/led_color",
                ]
            )

        if cmds:
            self.exec(" && ".join(cmds))
            self._remember_port_colors(port_colors)

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
