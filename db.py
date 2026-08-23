import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'parcelpilot.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('DROP TABLE IF EXISTS accounts')
    c.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            account_name TEXT,
            plan TEXT,
            status TEXT,
            csm TEXT,
            contract_file TEXT,
            premium_support TEXT,
            notes TEXT
        )
    ''')
    c.execute('DROP TABLE IF EXISTS orders')
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            account_id TEXT,
            carrier TEXT,
            status TEXT,
            booked_at TEXT,
            pickup_window_start TEXT,
            pickup_window_end TEXT,
            pickup_actual_at TEXT,
            shipment_fee_inr REAL,
            carrier_fault TEXT,
            customer_fault TEXT,
            cancellation_requested_at TEXT,
            notes TEXT
        )
    ''')
    c.execute('DROP TABLE IF EXISTS tickets')
    c.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            account_id TEXT,
            created_at TEXT,
            status TEXT,
            subject TEXT,
            description TEXT,
            channel TEXT,
            assigned_to TEXT,
            last_customer_message_at TEXT,
            historical_resolution TEXT
        )
    ''')
    
    c.execute('DROP TABLE IF EXISTS documents')
    c.execute('''
        CREATE VIRTUAL TABLE documents USING fts5(
            text,
            chunk_id UNINDEXED,
            source_name UNINDEXED,
            page_number UNINDEXED,
            source_type UNINDEXED,
            account_id UNINDEXED,
            customer_scope UNINDEXED,
            is_deprecated UNINDEXED,
            effective_from UNINDEXED
        )
    ''')
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
