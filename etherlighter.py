#!/usr/bin/env python3
"""Python port of etherlighter.

Starts a local web UI, connects to a UniFi device over SSH, and writes the same
Etherlighting commands as the original Go implementation.
"""

from __future__ import annotations

import argparse
import colorsys
import html
import json
import logging
import os
import re
import signal
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_LISTEN = "localhost:8080"
DEFAULT_TEMPLATE = Path(__file__).with_name("web") / "index.go.html"
DEFAULT_PRIVATE_KEY = Path.home() / ".ssh" / "id_rsa"

MODES = {
    "cold_reset": ["0"],
    "warm_reset": ["1"],
    "boot_done": ["2"],
    "speed": ["10", "0"],
    "network": ["10", "1"],
    "poe": ["10", "2"],
    "device_type": ["10", "3"],
    "port_locate": ["10", "4"],
    "port_locate_unset": ["10", "5"],
}

GO_LAYOUT_TEMPLATE = """    <div>
      {{ range .Layout }} {{ $rows := . }}
      <div class="ports">
        {{ range $rows }} {{ $cols := . }}
        <div
          tabindex="0"
          class="port"
          data-index="{{ . }}"
          aria-label="Port {{ . }}"
        >
          <span class="port-idx">{{ . }}</span>
        </div>
        {{ end }}
      </div>
      {{ end }}
    </div>"""


@dataclass
class Config:
    dev_mode: bool
    listen_addr: str
    device_host: str
    device_port: int
    username: str
    password: str | None
    private_key_path: Path | None

    @property
    def device_addr(self) -> str:
        return f"{self.device_host}:{self.device_port}"


@dataclass
class Color:
    r: int
    g: int
    b: int

    def as_dict(self) -> dict[str, int]:
        return {"r": self.r, "g": self.g, "b": self.b}


@dataclass
class PortColor:
    index: int
    color: Color


@dataclass
class ClientInfo:
    hostname: str = ""
    ip: str = ""
    mac: str = ""
    model: str = ""
    ntp: str = ""
    status: str = ""
    uptime: str = ""
    version: str = ""
    layout: list[list[int]] | None = None


def parse_device_addr(raw: str) -> tuple[str, int]:
    if not raw:
        raise ValueError("missing option: device")

    if raw.startswith("["):
        end = raw.find("]")
        if end == -1:
            raise ValueError(f"invalid device address: {raw!r}")
        host = raw[1:end]
        rest = raw[end + 1 :]
        if rest.startswith(":"):
            return host, parse_port(rest[1:])
        if rest:
            raise ValueError(f"invalid device address: {raw!r}")
        return host, 22

    if raw.count(":") == 1:
        host, port = raw.rsplit(":", 1)
        if port.isdigit():
            return host, parse_port(port)

    return raw, 22


def parse_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid port: {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"invalid port: {port}")
    return port


def parse_listen_addr(raw: str) -> tuple[str, int]:
    host, port = parse_device_addr(raw)
    return host, port


def parse_color(value: Any) -> Color:
    if not isinstance(value, dict):
        raise ValueError("color must be an object")

    try:
        color = Color(r=int(value["r"]), g=int(value["g"]), b=int(value["b"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("color must contain integer r, g and b values") from exc

    for channel_name, channel_value in (
        ("r", color.r),
        ("g", color.g),
        ("b", color.b),
    ):
        if not 0 <= channel_value <= 255:
            raise ValueError(f"color channel {channel_name} must be between 0 and 255")

    return color


def parse_port_colors(value: Any) -> list[PortColor]:
    if not isinstance(value, list):
        raise ValueError("request body must be a list")

    port_colors: list[PortColor] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("port color entries must be objects")
        try:
            index = int(item["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("port color entries must contain an integer index") from exc
        if index < 1:
            raise ValueError("port index must be greater than 0")
        port_colors.append(PortColor(index=index, color=parse_color(item.get("color"))))

    return port_colors


def to_range(start: int, end: int, skip: int) -> list[int]:
    return list(range(start, end + 1, skip))


def layout_for_model(model: str) -> list[list[int]]:
    layouts = {
        "USW-Pro-Max-24-PoE": [to_range(1, 24, 1)],
        "USW-Pro-Max-48-PoE": [to_range(1, 47, 2), to_range(2, 48, 2)],
        "USW-Pro-Max-16-PoE": [to_range(1, 16, 1)],
        "USW-Pro-Max-48": [to_range(1, 47, 2), to_range(2, 48, 2)],
        "USW-Pro-Max-24": [to_range(1, 24, 1)],
        "USW-Pro-Max-16": [to_range(1, 16, 1)],
    }
    return layouts.get(model, [])


class DeviceClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._ssh: Any | None = None
        self._lock = threading.Lock()
        self._color_lock = threading.Lock()
        self._last_port_colors: dict[int, Color] = {}
        self._known_ports: list[int] = []
        self._animation_lock = threading.Lock()
        self._animation_stop: threading.Event | None = None
        self._animation_thread: threading.Thread | None = None
        self._animation_pattern: str | None = None

    def connect(self) -> None:
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError(
                "missing dependency: paramiko. Install it with "
                "`python3 -m pip install -r requirements.txt`."
            ) from exc

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs: dict[str, Any] = {
            "hostname": self.cfg.device_host,
            "port": self.cfg.device_port,
            "username": self.cfg.username,
            "timeout": 10,
            "banner_timeout": 10,
            "auth_timeout": 20,
            "allow_agent": True,
            "look_for_keys": False,
        }

        if self.cfg.password:
            kwargs["password"] = self.cfg.password

        if self.cfg.private_key_path is not None:
            kwargs["key_filename"] = str(self.cfg.private_key_path.expanduser())

        client.connect(**kwargs)
        self._ssh = client

    def close(self) -> None:
        self.stop_color_cycle()
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None

    def exec(self, cmd: str) -> str:
        if self._ssh is None:
            raise RuntimeError("not connected")

        with self._lock:
            _, stdout, stderr = self._ssh.exec_command(cmd)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            status = stdout.channel.recv_exit_status()

        if status != 0:
            details = err.strip() or out.strip()
            raise RuntimeError(f"command failed with exit status {status}: {details}")

        return out

    def info(self) -> ClientInfo:
        output = self.exec("mca-cli-op info")
        info = ClientInfo(layout=[])

        for line in output.splitlines():
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            key, value = parts[0].strip(), parts[1].strip()
            if key == "Hostname":
                info.hostname = value
            elif key == "IP Address":
                info.ip = value
            elif key == "MAC Address":
                info.mac = value
            elif key == "Model":
                info.model = value
            elif key == "NTP":
                info.ntp = value
            elif key == "Status":
                info.status = value
            elif key == "Uptime":
                info.uptime = value
            elif key == "Version":
                info.version = value

        info.layout = layout_for_model(info.model)
        with self._color_lock:
            self._known_ports = [port for row in info.layout for port in row]
        return info

    def system_config(self) -> dict[str, dict[str, str]]:
        output = self.exec("cat /tmp/system.cfg")
        config = {"etherlight": {"behavior": "", "brightness": "", "mode": ""}}

        for line in output.splitlines():
            parts = line.split("=", 1)
            if len(parts) != 2:
                continue
            key, value = parts[0].strip(), parts[1].strip()
            if key == "switch.etherlight.behavior":
                config["etherlight"]["behavior"] = value
            elif key == "switch.etherlight.brightness":
                config["etherlight"]["brightness"] = value
            elif key == "switch.etherlight.mode":
                config["etherlight"]["mode"] = value

        return config

    def set_mode(self, mode: str) -> None:
        self.stop_color_cycle()
        args = MODES.get(mode)
        if args is None:
            raise ValueError(f"unsupported mode: {mode}")

        self.set_led_mode(1)
        self.exec(f"echo {' '.join(args)} > /proc/led/led_config")
        with self._color_lock:
            self._last_port_colors.clear()

    def set_all_ports(self, color: Color, brightness: int = 100) -> None:
        self.stop_color_cycle()
        self._set_all_ports(color, brightness)
        self._remember_all_ports_color(color)

    def _set_all_ports(self, color: Color, brightness: int = 100) -> None:
        if not 0 <= brightness <= 100:
            raise ValueError("brightness must be between 0 and 100")

        self.set_led_mode(0)
        self._set_all_ports_color(color, brightness)

    def _set_all_ports_color(self, color: Color, brightness: int = 100) -> None:
        self.exec(
            "echo '%02X %02X %02X %d' > /proc/led/led_all_port_code"
            % (color.r, color.g, color.b, brightness)
        )

    def set_port_colors(self, port_colors: list[PortColor]) -> None:
        self.stop_color_cycle()
        self._set_port_colors(port_colors)

    def _set_port_colors(self, port_colors: list[PortColor], reset_mode: bool = True) -> None:
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

    def set_led_mode(self, mode: int) -> None:
        self.exec(f"echo {mode} > /proc/led/led_mode")

    def start_color_cycle(
        self,
        interval_seconds: float = 0.2,
        brightness: int = 100,
        steps: int = 96,
        pattern: str = "all",
    ) -> None:
        if not 0.05 <= interval_seconds <= 5:
            raise ValueError("interval must be between 0.05 and 5 seconds")
        if not 1 <= steps <= 720:
            raise ValueError("steps must be between 1 and 720")
        if not 0 <= brightness <= 100:
            raise ValueError("brightness must be between 0 and 100")
        if pattern not in {"all", "offset"}:
            raise ValueError("pattern must be either all or offset")

        self.stop_color_cycle()

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_color_cycle,
            args=(stop_event, interval_seconds, brightness, steps, pattern),
            daemon=True,
            name="etherlighter-color-cycle",
        )
        with self._animation_lock:
            self._animation_stop = stop_event
            self._animation_thread = thread
            self._animation_pattern = pattern
        thread.start()

    def stop_color_cycle(self) -> bool:
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

    def color_cycle_running(self) -> bool:
        with self._animation_lock:
            thread = self._animation_thread
            return thread is not None and thread.is_alive()

    def color_cycle_pattern(self) -> str | None:
        with self._animation_lock:
            thread = self._animation_thread
            if thread is not None and thread.is_alive():
                return self._animation_pattern
            return None

    def _run_color_cycle(
        self,
        stop_event: threading.Event,
        interval_seconds: float,
        brightness: int,
        steps: int,
        pattern: str,
    ) -> None:
        try:
            self.set_led_mode(0)
            step = 0
            while not stop_event.is_set():
                if pattern == "offset":
                    self._set_offset_cycle_frame(step, steps)
                else:
                    color = color_from_hue((step % steps) / steps)
                    self._set_all_ports_color(color, brightness)
                    self._remember_all_ports_color(color)
                step += 1
                stop_event.wait(interval_seconds)
        except Exception:
            logging.exception("color cycle failed")
            stop_event.set()

    def _set_offset_cycle_frame(self, step: int, steps: int) -> None:
        ports = self._animation_ports()
        if not ports:
            raise RuntimeError("cannot run offset cycle without a known port layout")

        port_colors = [
            PortColor(
                index=port,
                color=color_from_hue(((step + offset * steps / len(ports)) % steps) / steps),
            )
            for offset, port in enumerate(ports)
        ]
        self._set_port_colors(port_colors, reset_mode=False)

    def _animation_ports(self) -> list[int]:
        with self._color_lock:
            if self._known_ports:
                return list(self._known_ports)
            return sorted(self._last_port_colors)

    def _remember_all_ports_color(self, color: Color) -> None:
        with self._color_lock:
            if self._known_ports:
                self._last_port_colors = {port: color for port in self._known_ports}

    def _remember_port_colors(self, port_colors: list[PortColor]) -> None:
        with self._color_lock:
            for port_color in port_colors:
                self._last_port_colors[port_color.index] = port_color.color

    def port_color_snapshot(self) -> dict[str, Any]:
        if self.color_cycle_running():
            with self._color_lock:
                cycle_colors = dict(self._last_port_colors)
            return {
                "source": "cycle",
                "pattern": self.color_cycle_pattern(),
                "colors": encode_port_colors(cycle_colors),
            }

        device_colors = self.read_port_colors_from_device()
        if device_colors:
            return {
                "source": "device",
                "colors": encode_port_colors(device_colors),
            }

        with self._color_lock:
            session_colors = dict(self._last_port_colors)

        if session_colors:
            return {
                "source": "session",
                "colors": encode_port_colors(session_colors),
            }

        return {
            "source": "unknown",
            "colors": [],
        }

    def read_port_colors_from_device(self) -> dict[int, Color]:
        output = self.exec(
            "for file in /proc/led/led_code /proc/led/led_color; do "
            'echo "__ETHERLIGHTER_FILE__${file}"; '
            'cat "${file}" 2>/dev/null || true; '
            "done"
        )
        return parse_device_port_colors(output)


def encode_port_colors(colors: dict[int, Color]) -> list[dict[str, Any]]:
    return [
        {"index": index, "color": color.as_dict()}
        for index, color in sorted(colors.items())
    ]


def parse_device_port_colors(output: str) -> dict[int, Color]:
    colors: dict[int, Color] = {}
    channels: dict[int, dict[str, int]] = {}

    code_pattern = re.compile(
        r"^\s*(\d+)\s+([0-9a-fA-F]{1,2})\s+([0-9a-fA-F]{1,2})\s+([0-9a-fA-F]{1,2})(?:\s+\d+)?\s*$"
    )
    channel_pattern = re.compile(r"^\s*(\d+)\s+([rgb])\s+(\d+)\s*$", re.IGNORECASE)

    for line in output.splitlines():
        code_match = code_pattern.match(line)
        if code_match:
            index = int(code_match.group(1))
            colors[index] = Color(
                r=int(code_match.group(2), 16),
                g=int(code_match.group(3), 16),
                b=int(code_match.group(4), 16),
            )
            continue

        channel_match = channel_pattern.match(line)
        if channel_match:
            index = int(channel_match.group(1))
            channel = channel_match.group(2).lower()
            raw_value = int(channel_match.group(3))
            channels.setdefault(index, {})[channel] = led_value_to_rgb_channel(raw_value)

    for index, channel_values in channels.items():
        if {"r", "g", "b"}.issubset(channel_values):
            colors[index] = Color(
                r=channel_values["r"],
                g=channel_values["g"],
                b=channel_values["b"],
            )

    return colors


def led_value_to_rgb_channel(value: int) -> int:
    if value > 25500:
        return max(0, min(255, round(value / 257)))
    return max(0, min(255, round(value / 100)))


def color_from_hue(hue: float) -> Color:
    r, g, b = colorsys.hsv_to_rgb(hue, 1, 1)
    return Color(r=round(r * 255), g=round(g * 255), b=round(b * 255))


def render_layout(layout: list[list[int]] | None) -> str:
    rows: list[str] = ["    <div>"]
    for port_row in layout or []:
        rows.append('      <div class="ports">')
        for port in port_row:
            escaped_port = html.escape(str(port))
            rows.extend(
                [
                    "        <div",
                    '          tabindex="0"',
                    '          class="port"',
                    f'          data-index="{escaped_port}"',
                    f'          aria-label="Port {escaped_port}"',
                    "        >",
                    f'          <span class="port-idx">{escaped_port}</span>',
                    "        </div>",
                ]
            )
        rows.append("      </div>")
    rows.append("    </div>")
    return "\n".join(rows)


def render_index(template: str, info: ClientInfo) -> bytes:
    page = template.replace(GO_LAYOUT_TEMPLATE, render_layout(info.layout))
    replacements = {
        "{{ .IP }}": info.ip,
        "{{ .Hostname }}": info.hostname,
        "{{ .Model }}": info.model,
        "{{ .Uptime }}": info.uptime,
    }
    for needle, value in replacements.items():
        page = page.replace(needle, html.escape(value))

    page = re.sub(r"\{\{[^}]+\}\}", "", page)
    return page.encode("utf-8")


class EtherlighterHandler(BaseHTTPRequestHandler):
    server: "EtherlighterServer"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/port-colors":
            try:
                self.send_json(self.server.client.port_color_snapshot())
            except Exception as exc:
                self.send_error(500, str(exc))
            return

        if path != "/":
            self.send_error(404, "not found")
            return

        try:
            template = self.server.load_template()
            info = self.server.client.info()
            body = render_index(template, info)
        except Exception as exc:
            self.send_error(500, str(exc))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self.read_json()
            if path == "/api/port-colors":
                self.server.client.set_port_colors(parse_port_colors(body))
            elif path == "/api/cycle":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")

                enabled = bool(body.get("enabled", True))
                if enabled:
                    interval = float(body.get("interval", 0.2))
                    brightness = int(body.get("brightness", 100))
                    pattern = str(body.get("pattern", "all"))
                    self.server.client.start_color_cycle(
                        interval_seconds=interval,
                        brightness=brightness,
                        pattern=pattern,
                    )
                else:
                    self.server.client.stop_color_cycle()
            elif path == "/api/mode":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                mode = str(body.get("mode", ""))
                self.server.client.set_mode(mode)
            else:
                self.send_error(404, "not found")
                return
        except Exception as exc:
            self.send_error(500, str(exc))
            return

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, value: Any) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> Any:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("empty request body")
        return json.loads(self.rfile.read(content_length))

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)


class EtherlighterServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        client: DeviceClient,
        template_path: Path,
        dev_mode: bool,
    ) -> None:
        super().__init__(server_address, EtherlighterHandler)
        self.client = client
        self.template_path = template_path
        self.dev_mode = dev_mode
        self._template = template_path.read_text(encoding="utf-8")

    def load_template(self) -> str:
        if self.dev_mode:
            return self.template_path.read_text(encoding="utf-8")
        return self._template


def load_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Control UniFi Etherlighting over SSH.")
    parser.add_argument("-dev", "--dev", action="store_true", help="reload web assets on each request")
    parser.add_argument(
        "-listen",
        "--listen",
        default=DEFAULT_LISTEN,
        help="HTTP listening address as <ip>[:<port>] (default: localhost:8080)",
    )
    parser.add_argument(
        "-device",
        "--device",
        required=True,
        help="UniFi device address as <ip>[:<port>]",
    )
    parser.add_argument("-user", "--user", required=True, help="username for SSH authentication")
    parser.add_argument(
        "-pass",
        "--password",
        "--pass",
        dest="password",
        default=os.environ.get("ETHERLIGHTER_PASSWORD"),
        help="password for SSH authentication (or ETHERLIGHTER_PASSWORD)",
    )
    parser.add_argument(
        "-pk",
        "--key",
        "--pk",
        dest="private_key_path",
        default=None,
        help="path to private key for SSH authentication",
    )

    args = parser.parse_args(argv)
    device_host, device_port = parse_device_addr(args.device)

    private_key_path = Path(args.private_key_path).expanduser() if args.private_key_path else None
    if private_key_path is None and DEFAULT_PRIVATE_KEY.exists():
        private_key_path = DEFAULT_PRIVATE_KEY

    return Config(
        dev_mode=args.dev,
        listen_addr=args.listen,
        device_host=device_host,
        device_port=device_port,
        username=args.user,
        password=args.password,
        private_key_path=private_key_path,
    )


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(argv)
    listen_host, listen_port = parse_listen_addr(cfg.listen_addr)

    logging.info("connecting to %s", cfg.device_addr)
    client = DeviceClient(cfg)
    client.connect()
    logging.info("connected")

    server = EtherlighterServer(
        (listen_host, listen_port),
        client=client,
        template_path=DEFAULT_TEMPLATE,
        dev_mode=cfg.dev_mode,
    )

    def shutdown(_signum: int, _frame: Any) -> None:
        logging.info("shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        logging.info("listening on http://%s:%d", listen_host, listen_port)
        server.serve_forever()
    finally:
        server.server_close()
        client.close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        logging.error("failed: %s", exc)
        raise SystemExit(1)
