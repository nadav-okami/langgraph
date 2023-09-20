import time
from typing import Iterator

import pytest
from pytest_mock import MockerFixture

from permchain.connection import PubSubMessage
from permchain.connection_inmemory import InMemoryPubSubConnection
from permchain.pubsub import PubSub
from permchain.topic import RunnableSubscriber, Topic


def clean_log(logs: Iterator[PubSubMessage]) -> list[PubSubMessage]:
    rm_keys = ["published_at", "correlation_id"]

    return [{k: v for k, v in m.items() if k not in rm_keys} for m in logs]


def test_invoke_single_process_in_out(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain = Topic.IN.subscribe() | add_one | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(chain, connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}
    # Then invoke pubsub
    assert pubsub.invoke(2) == 3
    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_invoke_two_processes_in_out(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topic_one = Topic("one")
    chain_one = Topic.IN.subscribe() | add_one | topic_one.publish()
    chain_two = topic_one.subscribe() | add_one | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(chain_one, chain_two, connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}
    # Then invoke pubsub
    assert pubsub.invoke(2) == 4
    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_batch_two_processes_in_out(mocker: MockerFixture):
    def add_one_with_delay(inp: int) -> int:
        time.sleep(inp / 10)
        return inp + 1

    topic_one = Topic("one")
    chain_one = Topic.IN.subscribe() | add_one_with_delay | topic_one.publish()
    chain_two = topic_one.subscribe() | add_one_with_delay | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(chain_one, chain_two, connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}
    # Then invoke pubsub
    assert pubsub.batch([3, 2, 1, 3, 5]) == [5, 4, 3, 5, 7]
    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


@pytest.mark.skip("TODO")
def test_stream_two_processes_in_out_interrupt(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topic_one = Topic("one")
    chain_one = Topic.IN.subscribe() | add_one | topic_one.publish()
    chain_two = (
        topic_one.subscribe()
        | {"plus_one": add_one, "original": Topic.IN.current()}
        | Topic.OUT.publish()
    )

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(chain_one, chain_two, connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # stream() until step one
    msg_one: PubSubMessage = None
    for msg in pubsub.stream(2):
        if msg["topic"] == "one":
            msg_one = msg
            break

    # resume stream() with the message from step one
    # this picks up where the first left off, and produces same result as
    # `test_invoke_two_processes_in_out`
    assert clean_log(pubsub.stream(msg_one)) == [
        {"value": 3, "topic": "one", "correlation_value": 2},
        {
            "value": {"plus_one": 4, "original": 2},
            "topic": "__out__",
            "correlation_value": 2,
        },
    ]
    # listeners are cleared
    assert conn.listeners == {}


def test_invoke_many_processes_in_out(mocker: MockerFixture):
    test_size = 100

    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topics: list[Topic] = [Topic("zero")]
    chains: list[RunnableSubscriber] = [
        Topic.IN.subscribe() | add_one | topics[0].publish()
    ]
    for i in range(test_size - 2):
        topics.append(Topic(str(i)))
        chains.append(topics[-2].subscribe() | add_one | topics[-1].publish())
    chains.append(topics[-1].subscribe() | add_one | Topic.OUT.publish())

    # Chains can be invoked directly for testing
    for chain in chains:
        assert chain.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=chains, connection=conn)

    for _ in range(10):
        # Using in-memory conn internals to make assertions about pubsub
        # If we start with 0 listeners
        assert conn.listeners == {}
        # Then invoke pubsub
        assert pubsub.invoke(2) == 2 + test_size
        # After invoke returns the listeners were cleaned up
        assert conn.listeners == {}


def test_batch_many_processes_in_out(mocker: MockerFixture):
    test_size = 100

    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topics: list[Topic] = [Topic("zero")]
    chains: list[RunnableSubscriber] = [
        Topic.IN.subscribe() | add_one | topics[0].publish()
    ]
    for i in range(test_size - 2):
        topics.append(Topic(str(i)))
        chains.append(topics[-2].subscribe() | add_one | topics[-1].publish())
    chains.append(topics[-1].subscribe() | add_one | Topic.OUT.publish())

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=chains, connection=conn)

    # TODO this occasionally fails, eg. with output [102, 101, None, 104, 105]

    for _ in range(10):
        # Using in-memory conn internals to make assertions about pubsub
        # If we start with 0 listeners
        assert conn.listeners == {}
        # Then invoke pubsub
        assert pubsub.batch([2, 1, 3, 4, 5]) == [
            2 + test_size,
            1 + test_size,
            3 + test_size,
            4 + test_size,
            5 + test_size,
        ]
        # After invoke returns the listeners were cleaned up
        assert conn.listeners == {}


def test_invoke_two_processes_two_in_two_out(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    chain_one = Topic.IN.subscribe() | add_one | Topic.OUT.publish()
    chain_two = Topic.IN.subscribe() | add_one | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=(chain_one, chain_two), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    # We get only one of the two return values, as computation is closed
    # as soon as we publish to OUT for the first time
    assert pubsub.invoke(2) == 3

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_invoke_two_processes_two_in_join_two_out(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    add_10_each = mocker.Mock(side_effect=lambda x: sorted(y + 10 for y in x))
    topic_one = Topic("one")
    topic_two = Topic("two")
    chain_one = Topic.IN.subscribe() | add_one | topic_one.publish()
    chain_two = topic_one.subscribe() | add_one | topic_two.publish()
    chain_three = Topic.IN.subscribe() | add_one | topic_two.publish()
    chain_four = topic_two.join() | add_10_each | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_four.invoke([2, 3]) == [12, 13]

    conn = InMemoryPubSubConnection()
    pubsub = PubSub((chain_one, chain_two, chain_three, chain_four), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    # We get a single array result as chain_four waits for all publishers to finish
    # before operating on all elements published to topic_two as an array
    assert pubsub.invoke(2) == [13, 14]

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_stream_join_then_subscribe(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    add_10_each = mocker.Mock(side_effect=lambda x: [y + 10 for y in x])

    topic_one = Topic("one")
    topic_two = Topic("two")

    chain_one = Topic.IN.subscribe() | add_10_each | topic_one.publish_each()
    chain_two = topic_one.join() | sum | topic_two.publish()
    chain_three = topic_two.subscribe() | add_one | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_two.invoke([2, 3]) == 5
    assert chain_three.invoke(5) == 6

    conn = InMemoryPubSubConnection()
    pubsub = PubSub((chain_one, chain_two, chain_three), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    # We get a single array result as chain_four waits for all publishers to finish
    # before operating on all elements published to topic_two as an array
    assert clean_log(pubsub.stream([2, 3])) == [
        {"value": [2, 3], "topic": "__in__", "correlation_value": [2, 3]},
        {"value": 12, "topic": "one", "correlation_value": [2, 3]},
        {"value": 13, "topic": "one", "correlation_value": [2, 3]},
        {"value": 25, "topic": "two", "correlation_value": [2, 3]},
        {"value": 26, "topic": "__out__", "correlation_value": [2, 3]},
    ]

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_stream_join_then_call_other_pubsub(mocker: MockerFixture):
    conn = InMemoryPubSubConnection()
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    inner_pubsub = PubSub(
        Topic.IN.subscribe() | add_one | Topic.OUT.publish(), connection=conn
    )

    add_10_each = mocker.Mock(side_effect=lambda x: [y + 10 for y in x])

    topic_one = Topic("one")
    topic_two = Topic("two")

    chain_one = Topic.IN.subscribe() | add_10_each | topic_one.publish_each()
    chain_two = topic_one.join() | inner_pubsub.map() | sorted | topic_two.publish()
    chain_three = topic_two.subscribe() | sum | Topic.OUT.publish()

    pubsub = PubSub((chain_one, chain_two, chain_three), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    assert clean_log(pubsub.stream([2, 3])) == [
        {"value": [2, 3], "topic": "__in__", "correlation_value": [2, 3]},
        {"value": 12, "topic": "one", "correlation_value": [2, 3]},
        {"value": 13, "topic": "one", "correlation_value": [2, 3]},
        {"value": [13, 14], "topic": "two", "correlation_value": [2, 3]},
        {"value": 27, "topic": "__out__", "correlation_value": [2, 3]},
    ]

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_stream_subscribe_then_call_other_pubsub(mocker: MockerFixture):
    conn = InMemoryPubSubConnection()
    add_one = mocker.Mock(side_effect=lambda x: x + 1)

    inner_pubsub = PubSub(
        Topic.IN.subscribe() | add_one | Topic.OUT.publish(), connection=conn
    )

    add_10_each = mocker.Mock(side_effect=lambda x: [y + 10 for y in x])

    topic_one = Topic("one")
    topic_two = Topic("two")

    chain_one = Topic.IN.subscribe() | add_10_each | topic_one.publish_each()
    chain_two = topic_one.subscribe() | inner_pubsub | topic_two.publish()
    chain_three = topic_two.join() | sorted | sum | Topic.OUT.publish()

    pubsub = PubSub((chain_one, chain_two, chain_three), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    log = clean_log(pubsub.stream([2, 3]))
    assert len(log) == 6
    assert log[0] == {"value": [2, 3], "topic": "__in__", "correlation_value": [2, 3]}
    assert log[5] == {"value": 27, "topic": "__out__", "correlation_value": [2, 3]}

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_stream_two_processes_one_in_two_out(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topic_one = Topic("one")
    # Topic.publish() is passthrough so we can publish to multiple topics in sequence
    chain_one = (
        Topic.IN.subscribe() | add_one | Topic.OUT.publish() | topic_one.publish()
    )
    chain_two = topic_one.subscribe() | add_one | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=(chain_one, chain_two), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    # pubsub stopped executing after publishing to OUT, so only one value is returned
    assert clean_log(pubsub.stream(2)) == [
        {"value": 2, "topic": "__in__", "correlation_value": 2},
        {"value": 3, "topic": "__out__", "correlation_value": 2},
    ]

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_invoke_two_processes_no_out(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topic_one = Topic("one")
    chain_one = Topic.IN.subscribe() | add_one | topic_one.publish()
    chain_two = topic_one.subscribe() | add_one

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=(chain_one, chain_two), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    # It finishes executing (once no more messages being published)
    # but returns nothing, as nothing was published to OUT topic
    assert pubsub.invoke(2) is None

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


def test_invoke_two_processes_no_in(mocker: MockerFixture):
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topic_one = Topic("one")
    chain_one = topic_one.subscribe() | add_one | Topic.OUT.publish()
    chain_two = topic_one.subscribe() | add_one | Topic.OUT.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=(chain_one, chain_two), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}

    # Then invoke pubsub
    # It returns without any output as there is nothing to run
    assert pubsub.invoke(2) is None

    # After invoke returns the listeners were cleaned up
    assert conn.listeners == {}


@pytest.mark.skip("TODO")
def test_invoke_two_processes_simple_cycle(mocker: MockerFixture) -> None:
    add_one = mocker.Mock(side_effect=lambda x: x + 1)
    topic_one = Topic("one")
    chain_one = Topic.IN.subscribe() | add_one | topic_one.publish()
    chain_two = topic_one.subscribe() | add_one | topic_one.publish()

    # Chains can be invoked directly for testing
    assert chain_one.invoke(2) == 3
    assert chain_two.invoke(2) == 3

    conn = InMemoryPubSubConnection()
    pubsub = PubSub(processes=(chain_one, chain_two), connection=conn)

    # Using in-memory conn internals to make assertions about pubsub
    # If we start with 0 listeners
    assert conn.listeners == {}
    # Then invoke pubsub
    with pytest.raises(RecursionError):
        pubsub.invoke(2)
    # After invoke returns the listeners were cleaned up
    for key in conn.listeners:
        assert not conn.listeners[key]