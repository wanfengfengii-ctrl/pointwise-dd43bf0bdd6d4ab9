from dataclasses import dataclass

from storage import identifier


@dataclass(frozen=True)
class ReadingOrigin:
    order_id: str
    revision: int
    instrument: str
    record: str
    initial_record: str


def initial_origin(order_id: str, instrument: str, record: str) -> ReadingOrigin:
    return ReadingOrigin(identifier(order_id), 1, identifier(instrument), identifier(record), record)


def corrected_origin(previous: ReadingOrigin, record: str) -> ReadingOrigin:
    return ReadingOrigin(
        previous.order_id, previous.revision + 1, previous.instrument, identifier(record), previous.initial_record
    )
