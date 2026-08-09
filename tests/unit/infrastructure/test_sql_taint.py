"""Step 1 — E-01: SQL built into a local, then executed.

The regex rule matches `execute\\s*\\([^)]*\\+` on one line. Nobody writes it
on one line. The evaluation harness charged the miss as the whole of the
committed recall gap, and this is the pass that closes it.
"""

from code_reviewer.infrastructure.analyzers.sql_taint import find_sql_taint


def _lines(source: str) -> list[int]:
    return [query.line_number for query in find_sql_taint(source)]


# -- what is reported --------------------------------------------------------


def test_concatenation_into_a_local_is_reported_where_the_string_was_built():
    """Not where `execute` was called.

    The defect is the concatenation. Pointing at the execution sends the
    reader to the line that is correct in isolation.
    """
    source = "\n".join(
        [
            "def find(connection, name):",
            '    query = "SELECT * FROM users WHERE name = \'" + name + "\'"',
            "    return connection.execute(query).fetchall()",
        ]
    )

    assert _lines(source) == [2]


def test_percent_formatting_into_a_local_is_reported():
    source = "\n".join(
        [
            "def find(cursor, city):",
            "    query = \"SELECT id FROM users WHERE city = '%s'\" % city",
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == [2]


def test_str_format_into_a_local_is_reported():
    source = "\n".join(
        [
            "def find(cursor, city):",
            '    query = "SELECT id FROM users WHERE city = {}".format(city)',
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == [2]


def test_an_f_string_into_a_local_is_reported():
    source = "\n".join(
        [
            "def find(cursor, city):",
            '    query = f"SELECT id FROM users WHERE city = {city}"',
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == [2]


def test_taint_follows_one_reassignment():
    source = "\n".join(
        [
            "def find(cursor, city):",
            '    built = "DELETE FROM users WHERE city = " + city',
            "    query = built",
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == [2]


def test_executemany_and_executescript_count_as_execution():
    for method in ("executemany", "executescript"):
        source = "\n".join(
            [
                "def run(cursor, value):",
                '    query = "INSERT INTO t VALUES (" + value + ")"',
                f"    cursor.{method}(query)",
            ]
        )

        assert _lines(source) == [2], method


def test_the_reported_variable_and_evidence_name_what_happened():
    source = "\n".join(
        [
            "def find(connection, name):",
            '    query = "SELECT * FROM users WHERE name = " + name',
            "    return connection.execute(query)",
        ]
    )

    tainted = find_sql_taint(source)[0]

    assert tainted.variable == "query"
    assert "SELECT" in tainted.evidence
    assert tainted.how == "concatenation"
    assert tainted.executed_at == 3


# -- what is not reported ----------------------------------------------------


def test_a_parameterised_query_is_not_reported():
    """The safe form. If this fires, the fix has cost more than it bought."""
    source = "\n".join(
        [
            "def find(cursor, name):",
            '    query = "SELECT * FROM users WHERE name = ?"',
            "    cursor.execute(query, (name,))",
        ]
    )

    assert _lines(source) == []


def test_a_constant_query_assigned_and_executed_is_not_reported():
    source = "\n".join(
        [
            "def all_users(cursor):",
            '    query = "SELECT * FROM users"',
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == []


def test_two_literals_concatenated_are_not_reported():
    """Nothing untrusted enters, however it is spelled."""
    source = "\n".join(
        [
            "def all_users(cursor):",
            '    query = "SELECT * FROM " + "users"',
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == []


def test_an_f_string_with_no_interpolation_is_not_reported():
    source = "\n".join(
        [
            "def all_users(cursor):",
            '    query = f"SELECT * FROM users"',
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == []


def test_a_tainted_string_that_is_never_executed_is_not_reported():
    """This analyzer is about queries, not about strings."""
    source = "\n".join(
        [
            "def label(name):",
            '    return "SELECT " + name',
        ]
    )

    assert _lines(source) == []


def test_a_string_with_no_sql_keyword_is_not_reported():
    source = "\n".join(
        [
            "def run(cursor, name):",
            '    message = "hello " + name',
            "    cursor.execute(message)",
        ]
    )

    assert _lines(source) == []


def test_reassignment_to_a_constant_clears_the_taint():
    source = "\n".join(
        [
            "def find(cursor, name):",
            '    query = "SELECT * FROM users WHERE name = " + name',
            '    query = "SELECT * FROM users"',
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == []


def test_a_variable_of_the_same_name_in_another_function_is_not_tainted():
    """Scopes are separate. A name reused elsewhere is a different variable,
    and treating it otherwise is how a taint pass earns its reputation."""
    source = "\n".join(
        [
            "def build(name):",
            '    query = "SELECT * FROM users WHERE name = " + name',
            "    return query",
            "",
            "",
            "def run(cursor, query):",
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == []


def test_execution_before_the_assignment_is_not_reported():
    source = "\n".join(
        [
            "def find(cursor, name):",
            "    cursor.execute(query)",
            '    query = "SELECT * FROM users WHERE name = " + name',
        ]
    )

    assert _lines(source) == []


# -- robustness --------------------------------------------------------------


def test_a_file_that_does_not_parse_contributes_nothing_and_raises_nothing():
    assert find_sql_taint("def broken(:\n    pass\n") == []


def test_an_empty_file_contributes_nothing():
    assert find_sql_taint("") == []


def test_a_tainted_query_inside_a_branch_is_still_found():
    source = "\n".join(
        [
            "def find(cursor, name, exact):",
            "    if exact:",
            '        query = "SELECT * FROM users WHERE name = " + name',
            "        cursor.execute(query)",
        ]
    )

    assert _lines(source) == [3]


def test_one_defect_is_reported_once_however_often_it_is_executed():
    source = "\n".join(
        [
            "def find(cursor, name):",
            '    query = "SELECT * FROM users WHERE name = " + name',
            "    cursor.execute(query)",
            "    cursor.execute(query)",
        ]
    )

    assert _lines(source) == [2]
