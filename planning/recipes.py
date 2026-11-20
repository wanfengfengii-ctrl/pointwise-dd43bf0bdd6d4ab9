from dataclasses import dataclass
import sqlite3

from storage import Conflict, atomic, decode_integer, encode_integer, identifier, require_transaction


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    multiplier: int
    offset: int


def create_recipes(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
            recipe_id TEXT PRIMARY KEY NOT NULL,
            multiplier TEXT NOT NULL,
            offset TEXT NOT NULL
        )
    ''')


def get_recipe(connection: sqlite3.Connection, recipe_id: str) -> Recipe | None:
    row = connection.execute('SELECT * FROM recipes WHERE recipe_id = ?', (recipe_id,)).fetchone()
    if row is None:
        return None
    return Recipe(row['recipe_id'], decode_integer(row['multiplier']), decode_integer(row['offset']))


def insert_recipe(connection: sqlite3.Connection, recipe: Recipe) -> None:
    require_transaction(connection)
    connection.execute(
        'INSERT INTO recipes VALUES (?, ?, ?)',
        (identifier(recipe.recipe_id), encode_integer(recipe.multiplier), encode_integer(recipe.offset)),
    )


def register_recipe(connection: sqlite3.Connection, recipe_id: str, multiplier: int, offset: int) -> Recipe:
    recipe = Recipe(identifier(recipe_id), multiplier, offset)
    encode_integer(multiplier)
    encode_integer(offset)
    with atomic(connection):
        existing = get_recipe(connection, recipe_id)
        if existing is None:
            insert_recipe(connection, recipe)
            return recipe
        if existing != recipe:
            raise Conflict(f'recipe version {recipe_id!r} already has coefficients')
        return existing
