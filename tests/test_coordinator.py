"""Tests for Etherlighter coordinator helpers."""

from __future__ import annotations

from custom_components.etherlighter.coordinator import (
    interval_to_transition_speed,
    transition_speed_to_interval,
)


def test_transition_speed_mapping_keeps_default_interval() -> None:
    assert transition_speed_to_interval(1) == 1.0
    assert transition_speed_to_interval(50) == 0.2
    assert transition_speed_to_interval(100) == 0.05


def test_transition_interval_mapping_keeps_default_speed() -> None:
    assert interval_to_transition_speed(1.0) == 1
    assert interval_to_transition_speed(0.2) == 50
    assert interval_to_transition_speed(0.05) == 100
