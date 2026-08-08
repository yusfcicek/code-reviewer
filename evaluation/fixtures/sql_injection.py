"""A repository layer that builds SQL by concatenation."""

import sqlite3


class CustomerRepository:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def find_by_name(self, name):
        query = "SELECT * FROM customers WHERE name = '" + name + "'"
        return self._connection.execute(query).fetchall()

    def find_by_city(self, city):
        cursor = self._connection.cursor()
        cursor.execute("SELECT id FROM customers WHERE city = '%s'" % city)
        return cursor.fetchall()
