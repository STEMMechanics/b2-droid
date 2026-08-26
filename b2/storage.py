"""SQLite connection service shared by B2 repositories."""

import contextlib
import sqlite3
from pathlib import Path


class DatabaseService:
    def __init__(self, filename):
        self.filename = str(filename)

    @contextlib.contextmanager
    def connection(self):
        Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.filename, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
