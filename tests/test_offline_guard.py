import os
import socket

import pytest


def test_outbound_connection_is_blocked() -> None:
    # 203.0.113.0/24 is reserved for documentation; the guard refuses before any packet.
    with pytest.raises(RuntimeError, match="offline test tried to connect"):
        socket.create_connection(("203.0.113.10", 443), timeout=1)


def test_provider_keys_are_not_visible_to_offline_tests() -> None:
    assert "OPENAI_API_KEY" not in os.environ
    assert "TYPESAFE_API_KEY" not in os.environ
