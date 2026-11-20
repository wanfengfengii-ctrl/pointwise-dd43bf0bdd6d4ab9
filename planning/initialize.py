import sqlite3

from planning.orders import create_orders
from planning.recipes import Recipe, create_recipes, get_recipe, insert_recipe
from planning.shifts import create_shifts
from storage import atomic


DEFAULT_RECIPE_ID = 'identity-v1'


def initialize_planning(connection: sqlite3.Connection) -> None:
    with atomic(connection):
        create_recipes(connection)
        create_shifts(connection)
        create_orders(connection)
        if get_recipe(connection, DEFAULT_RECIPE_ID) is None:
            insert_recipe(connection, Recipe(DEFAULT_RECIPE_ID, 1, 0))
