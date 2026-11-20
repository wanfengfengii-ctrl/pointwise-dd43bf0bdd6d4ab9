from bench.staging import StagedReading
from planning.orders import Order
from storage import Conflict, encode_integer, identifier, positive_revision


class SourceMismatch(Conflict):
    """A reading or its provenance does not belong to the planned order."""


def verify_provenance(order: Order, reading: StagedReading) -> None:
    origin = reading.origin
    if (reading.order_id, origin.order_id) != (order.order_id, order.order_id):
        raise SourceMismatch('reading and provenance must belong to the planned order')
    if origin.revision != reading.revision:
        raise SourceMismatch('provenance must name the staged revision')
    try:
        positive_revision(reading.revision)
        positive_revision(origin.revision)
        encode_integer(reading.raw)
        for value in (origin.instrument, origin.record, origin.initial_record):
            identifier(value)
    except ValueError as error:
        raise SourceMismatch('invalid staged reading or origin') from error
    if reading.revision == 1 and origin.record != origin.initial_record:
        raise SourceMismatch('the initial revision must identify its own original record')
