"""Share Task 2's isolated PostgreSQL fixture with WS8 evaluation tests.

Pytest discovers fixtures defined/imported by a directory's ``conftest.py``
for every sibling test module. Import the original fixture rather than
reimplementing preparation or cleanup, preserving Task 2's safety guarantees.
"""

from tests.integration.evaluation.test_fixture_preparation_postgres import (
    prepared_postgres as prepared_postgres,
)
