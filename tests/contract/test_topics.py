"""T011: topic node_id, payload node_id, and certificate identity MUST agree."""

import pytest

from energy_ingestion.contracts.topics import (
    CHANNELS,
    TOPIC_PREFIX,
    ContractError,
    check_identity,
    parse_topic,
    topic_for,
)


def test_prefix_and_channels_match_contracts_readme() -> None:
    assert TOPIC_PREFIX == "unmsm/energy/v1/nodes"
    assert set(CHANNELS) == {
        "measurements",
        "events",
        "status",
        "config",
        "acks/measurements",
    }


@pytest.mark.parametrize("channel", sorted(CHANNELS))
def test_topic_round_trip(channel: str) -> None:
    topic = topic_for("node-001", channel)
    assert topic == f"unmsm/energy/v1/nodes/node-001/{channel}"
    assert parse_topic(topic) == ("node-001", channel)


@pytest.mark.parametrize(
    "topic",
    [
        "unmsm/energy/v2/nodes/node-001/measurements",  # wrong major version
        "unmsm/energy/v1/nodes/node-001/unknown",
        "unmsm/energy/v1/nodes/Node-001/measurements",  # identifier is lowercase
        "unmsm/energy/v1/nodes/+/measurements",
        "unmsm/energy/v1/nodes/node-001/measurements/extra",
        "unmsm/energy/v1/nodes//measurements",
        "",
    ],
)
def test_malformed_topics_are_rejected(topic: str) -> None:
    with pytest.raises(ContractError) as exc:
        parse_topic(topic)
    assert exc.value.reason_code == "topic_invalid"


def test_topic_for_rejects_bad_identifier() -> None:
    with pytest.raises(ContractError):
        topic_for("node/001", "measurements")


def test_agreeing_identity_passes() -> None:
    topic = topic_for("node-001", "measurements")
    assert check_identity("node-001", topic, {"node_id": "node-001"}) == "node-001"


@pytest.mark.parametrize(
    ("cert", "topic_node", "payload_node"),
    [
        ("sim-001", "node-001", "node-001"),  # certificate differs
        ("node-001", "node-002", "node-001"),  # topic differs
        ("node-001", "node-001", "node-002"),  # payload differs
    ],
)
def test_any_disagreement_is_rejected(cert: str, topic_node: str, payload_node: str) -> None:
    with pytest.raises(ContractError) as exc:
        check_identity(cert, topic_for(topic_node, "measurements"), {"node_id": payload_node})
    assert exc.value.reason_code == "identity_mismatch"


def test_payload_without_node_id_is_rejected() -> None:
    with pytest.raises(ContractError) as exc:
        check_identity("node-001", topic_for("node-001", "status"), {})
    assert exc.value.reason_code == "identity_mismatch"
