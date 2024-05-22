import os
import sqlite3
import logging
import time
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv('DB_PATH')
MAX_DB_RETRIES = int(os.getenv('MAX_DB_RETRIES'))


class DatabaseManager:
    def __init__(self):
        self.db_path = DB_PATH

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.commit()
        self.conn.close()

    @staticmethod
    def db_operation_with_retry(operation, *args, **kwargs):
        attempts = 0
        while attempts < MAX_DB_RETRIES:
            try:
                return operation(*args, **kwargs)
            except sqlite3.Error as e:
                attempts += 1
                logging.error(f"SQLite error occurred: {e}. Retrying {attempts}/{MAX_DB_RETRIES}")
                time.sleep(1)  # Wait for 1 second before retrying
            except Exception as e:
                logging.error(f"An unexpected error occurred: {e}")
                raise  # Re-raise the exception if it's not an SQLite error
        raise sqlite3.Error(f"Operation failed after {MAX_DB_RETRIES} attempts.")

    def execute_query(self, query, parameters=()):
        def operation(cursor):
            cursor.execute(query, parameters)

        self.db_operation_with_retry(operation, self.cursor)

    def fetch_one(self):
        return self.db_operation_with_retry(self.cursor.fetchone)

    def fetch_all(self):
        return self.db_operation_with_retry(self.cursor.fetchall)

    def commit(self):
        self.db_operation_with_retry(self.conn.commit)
