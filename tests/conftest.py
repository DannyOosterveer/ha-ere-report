"""Fixtures for the ERE charging report tests."""

import pytest


@pytest.fixture
def recorder_mock(recorder_mock, enable_custom_integrations):
    """Set up the recorder before hass, then allow custom integrations."""
    return recorder_mock
