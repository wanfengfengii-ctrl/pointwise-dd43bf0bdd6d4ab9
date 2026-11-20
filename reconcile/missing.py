from dataclasses import dataclass

from planning.orders import Order
from receipt.readback import ReceivedItem
from storage import Conflict


@dataclass(frozen=True)
class ManifestLine:
    order_id: str
    sample: str
    recipe_id: str
    position: int
    item: ReceivedItem | None

    @property
    def missing(self) -> bool:
        return self.item is None


def classify_manifest_line(order: Order, item: ReceivedItem | None) -> ManifestLine:
    if item is not None and (item.order_id, item.recipe_id) != (order.order_id, order.recipe_id):
        raise Conflict('receipt does not match the planned manifest line')
    return ManifestLine(order.order_id, order.sample, order.recipe_id, order.position, item)


def list_missing_orders(lines: tuple[ManifestLine, ...]) -> tuple[str, ...]:
    return tuple(line.order_id for line in lines if line.missing)
