"""The safe spellings, all of them.

Where the Level 13 taint pass earns its false positives if it is going to.
"""

ALL_USERS = "SELECT id, name FROM users ORDER BY name"


def find_by_name(cursor, name):
    cursor.execute("SELECT * FROM users WHERE name = ?", (name,))
    return cursor.fetchall()


def find_by_city(cursor, city):
    query = "SELECT id FROM users WHERE city = ?"
    cursor.execute(query, (city,))
    return cursor.fetchall()


def everyone(cursor):
    cursor.execute(ALL_USERS)
    return cursor.fetchall()


def describe(user, city):
    label = "user " + user
    return label + " from " + city
