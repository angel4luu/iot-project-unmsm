"""MQTT topic layout and the identity rule (contracts/README.md)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from energy_ingestion.contracts.validate import ContractError

__all__ = [
    "CHANNELS",
    "TOPIC_PREFIX",
    "ContractError",
    "check_identity",
    "parse_topic",
    "topic_for",
]

TOPIC_PREFIX = "unmsm/energy/v1/nodes"
CHANNELS: tuple[str, ...] = ("measurements", "events", "status", "config", "acks/measurements")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def topic_for(node_id: str, channel: str) -> str:
    if not _IDENTIFIER.fullmatch(node_id):
        raise ContractError("topic_invalid", "node_id is not an identifier")
    if channel not in CHANNELS:
        raise ContractError("topic_invalid", f"unknown channel {channel!r}")
    return f"{TOPIC_PREFIX}/{node_id}/{channel}"


def parse_topic(topic: str) -> tuple[str, str]:
    """Split a concrete topic into (node_id, channel); wildcards are not accepted."""
    prefix = TOPIC_PREFIX + "/"
    if not topic.startswith(prefix):
        raise ContractError("topic_invalid", "wrong prefix or version")
    node_id, _, channel = topic.removeprefix(prefix).partition("/")
    if not _IDENTIFIER.fullmatch(node_id) or channel not in CHANNELS:
        raise ContractError("topic_invalid", "bad node_id or channel")
    return node_id, channel


def check_identity(cert_identity: str, topic: str, payload: Mapping[str, object]) -> str:
    """Return the node_id when certificate, topic, and payload agree; else raise."""
    topic_node, _ = parse_topic(topic)
    payload_node = payload.get("node_id")
    if not (cert_identity == topic_node == payload_node):
        raise ContractError("identity_mismatch", "certificate, topic, and payload node_id differ")
    return topic_node
