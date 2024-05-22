from DatabaseManager import DatabaseManager
from dotenv import load_dotenv
import os

load_dotenv()

DB_PATH = os.getenv('DB_PATH')


class SearchManager:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.search_interval = 10  # Static interval (10 minutes)
        self.initialize_database()

    def initialize_database(self):
        with self.db_manager as db:
            db.execute_query('''
                CREATE TABLE IF NOT EXISTS queries (
                    id INTEGER PRIMARY KEY,
                    search_text TEXT NOT NULL,
                    value INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL)
            ''')

    def add_search(self, search_text, value, channel_id):
        with self.db_manager as db:
            db.execute_query('SELECT * FROM queries WHERE search_text = ?', (search_text,))
            if not db.fetch_one():
                db.execute_query('INSERT INTO queries (search_text, value, channel_id) VALUES (?, ?, ?)',
                                 (search_text, value, channel_id))
            else:
                db.execute_query('UPDATE queries SET value = ? WHERE search_text = ? AND channel_id = ?',
                                 (value, search_text, channel_id))

    def delete_search(self, search_text, channel_id):
        with self.db_manager as db:
            db.execute_query('DELETE FROM queries WHERE search_text = ? AND channel_id = ?', (search_text, channel_id))

    def get_next_search(self):
        with self.db_manager as db:
            db.execute_query('SELECT * FROM queries ORDER BY id LIMIT 1')
            row = db.fetch_one()
            if row:
                # Rotate the search queries
                db.execute_query('DELETE FROM queries WHERE id = ?', (row[0],))
                db.execute_query('INSERT INTO queries (search_text, value, channel_id) VALUES (?, ?, ?)',
                                 (row[1], row[2], row[3]))
        return row

    def get_all_searches(self):
        searches = []
        with self.db_manager as db:
            db.execute_query('SELECT search_text FROM queries')
            rows = db.fetch_all()
            searches.extend(row[0] for row in rows)
            return searches
