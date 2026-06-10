"""Tests for the Etherlighter SSH API helpers."""

from __future__ import annotations

from custom_components.etherlighter.api import (
    Color,
    EtherlighterClient,
    EtherlighterError,
    HostKeyMismatch,
    _TrustOnFirstUsePolicy,
    color_from_hue,
    host_key_fingerprint,
)
from custom_components.etherlighter.const import CYCLE_PATTERN_OFFSET


class FakeKey:
    """Fake Paramiko host key."""

    def asbytes(self) -> bytes:
        return b"etherlighter-test-key"

    def get_name(self) -> str:
        return "ssh-ed25519"


class FakeHostKeys:
    """Fake Paramiko host-key registry."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, FakeKey]] = []

    def add(self, hostname: str, key_type: str, key: FakeKey) -> None:
        self.entries.append((hostname, key_type, key))


class FakeSshClient:
    """Fake Paramiko SSH client for host-key policy tests."""

    def __init__(self) -> None:
        self.host_keys = FakeHostKeys()

    def get_host_keys(self) -> FakeHostKeys:
        return self.host_keys


class FakeClient(EtherlighterClient):
    """Etherlighter client that records SSH commands instead of sending them."""

    def __init__(self) -> None:
        super().__init__(
            host="192.0.2.10",
            port=22,
            username="ubnt",
            password="password",
        )
        self.commands: list[str] = []
        self._known_ports = [1, 2, 3, 4]

    def connect(self) -> str:
        return "SHA256:test"

    def exec(self, cmd: str) -> str:
        self.commands.append(cmd)
        return ""


def test_host_key_fingerprint_uses_sha256() -> None:
    fingerprint = host_key_fingerprint(FakeKey())
    assert fingerprint.startswith("SHA256:")
    assert fingerprint == "SHA256:eDvs623v4zCZ3JyJTrGer1C4wW1JzZW8do1os5WY9EY"


def test_host_key_policy_trusts_first_key() -> None:
    policy = _TrustOnFirstUsePolicy(None)
    client = FakeSshClient()
    key = FakeKey()

    policy.missing_host_key(client, "switch.local", key)

    assert policy.observed_fingerprint == host_key_fingerprint(key)
    assert client.host_keys.entries == [("switch.local", "ssh-ed25519", key)]


def test_host_key_policy_accepts_matching_key() -> None:
    key = FakeKey()
    policy = _TrustOnFirstUsePolicy(host_key_fingerprint(key))
    client = FakeSshClient()

    policy.missing_host_key(client, "switch.local", key)

    assert client.host_keys.entries == [("switch.local", "ssh-ed25519", key)]


def test_host_key_policy_rejects_changed_key() -> None:
    policy = _TrustOnFirstUsePolicy("SHA256:changed")

    try:
        policy.missing_host_key(FakeSshClient(), "switch.local", FakeKey())
    except HostKeyMismatch as err:
        assert err.expected == "SHA256:changed"
        assert err.observed == host_key_fingerprint(FakeKey())
    else:  # pragma: no cover
        raise AssertionError("HostKeyMismatch was not raised")


def test_color_from_hue() -> None:
    assert color_from_hue(0) == Color(255, 0, 0)
    assert color_from_hue(1 / 3) == Color(0, 255, 0)
    assert color_from_hue(2 / 3) == Color(0, 0, 255)


def test_set_mode_emits_led_config_command() -> None:
    client = FakeClient()
    client.set_mode("network")
    assert client.commands == [
        "echo 1 > /proc/led/led_mode",
        "echo 10 1 > /proc/led/led_config",
    ]


def test_offset_cycle_frame_sets_each_port_to_different_color() -> None:
    client = FakeClient()
    client._set_offset_cycle_frame(step=0, steps=96)

    assert client.commands[0].startswith("echo 1 r")
    assert "echo 4 b" in client.commands[0]
    remembered = [color for _, color in sorted(client._last_port_colors.items())]
    assert len(remembered) == 4
    assert len(set(remembered)) == 4


def test_all_ports_color_command() -> None:
    client = FakeClient()
    client._set_all_ports_color(Color(255, 0, 127), 80)
    assert client.commands == ["echo 'FF 00 7F 80' > /proc/led/led_all_port_code"]


def test_static_color_stops_cycle_and_sets_led_mode() -> None:
    client = FakeClient()
    client.set_static_color(Color(1, 2, 3), 75)
    assert client.commands == [
        "echo 0 > /proc/led/led_mode",
        "echo '01 02 03 75' > /proc/led/led_all_port_code",
    ]


def test_offset_cycle_requires_known_ports() -> None:
    client = FakeClient()
    client._known_ports = []

    try:
        client.start_color_cycle(CYCLE_PATTERN_OFFSET)
    except EtherlighterError as err:
        assert "known port layout" in str(err)
    else:  # pragma: no cover
        raise AssertionError("EtherlighterError was not raised")
