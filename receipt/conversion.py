import sqlite3

from planning.orders import Order
from planning.recipes import get_recipe
from storage import NotFound, encode_integer


def convert_reading(connection: sqlite3.Connection, order: Order, raw: int) -> int:
    encode_integer(raw)
    recipe = get_recipe(connection, order.recipe_id)
    if recipe is None:
        raise NotFound(f'frozen recipe {order.recipe_id!r} is unavailable')
    return recipe.multiplier * raw + recipe.offset
