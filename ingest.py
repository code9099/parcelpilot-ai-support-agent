import os
import hashlib
import sqlite3
import pandas as pd
import fitz  # PyMuPDF
import uuid
import db

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

PDF_METADATA = {
    '01_Support_Policy_v3_CURRENT.pdf': {
        'source_type': 'current_policy', 'customer_scope': 'global', 'account_id': None, 'is_deprecated': 'false'
    },
    '02_Support_Policy_v2_DEPRECATED.pdf': {
        'source_type': 'deprecated_policy', 'customer_scope': 'global', 'account_id': None, 'is_deprecated': 'true'
    },
    '03_Cancellation_and_Service_Credit_SOP_v4.pdf': {
        'source_type': 'current_sop', 'customer_scope': 'global', 'account_id': None, 'is_deprecated': 'false'
    },
    '04_Product_Operations_Guide_and_Known_Issues.pdf': {
        'source_type': 'product_ops_guide', 'customer_scope': 'global', 'account_id': None, 'is_deprecated': 'false'
    },
    '05_Northstar_Logistics_Enterprise_Agreement.pdf': {
        'source_type': 'customer_agreement', 'customer_scope': 'NORTHSTAR', 'account_id': 'ACCT-001', 'is_deprecated': 'false'
    },
    '06_LumenWorks_Service_Agreement.pdf': {
        'source_type': 'customer_agreement', 'customer_scope': 'LUMENWORKS', 'account_id': 'ACCT-002', 'is_deprecated': 'false'
    }
}

def hash_file(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def get_source_hashes():
    files = os.listdir(DATA_DIR)
    hashes = {}
    for f in files:
        if f.endswith('.pdf') or f.endswith('.xlsx'):
            hashes[f] = hash_file(os.path.join(DATA_DIR, f))
    return hashes

def ingest():
    print("Hashing source files...")
    pre_hashes = get_source_hashes()
    
    db.init_db()
    conn = db.get_connection()
    c = conn.cursor()
    
    # Clear structured tables
    c.execute('DELETE FROM accounts')
    c.execute('DELETE FROM orders')
    c.execute('DELETE FROM tickets')

    print("Ingesting PDFs...")
    files = os.listdir(DATA_DIR)
    for f in files:
        if f.endswith('.pdf') and f in PDF_METADATA:
            filepath = os.path.join(DATA_DIR, f)
            meta = PDF_METADATA[f]
            doc = fitz.open(filepath)
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # Extract using blocks to preserve structural units (paragraphs, table rows)
                blocks = page.get_text('blocks')
                chunk_text = ""
                
                for b in blocks:
                    # PyMuPDF block format: (x0, y0, x1, y1, text, block_no, block_type)
                    # block_type == 0 means text
                    if b[6] == 0:
                        block_text = b[4].strip()
                        if not block_text:
                            continue
                        
                        if len(chunk_text) + len(block_text) > 1000:
                            if chunk_text:
                                chunk_id = str(uuid.uuid4())
                                c.execute('''
                                    INSERT INTO documents (text, chunk_id, source_name, page_number, source_type, account_id, customer_scope, is_deprecated, effective_from)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    chunk_text, chunk_id, f, page_num + 1, meta['source_type'], 
                                    meta['account_id'], meta['customer_scope'], meta['is_deprecated'], None
                                ))
                            chunk_text = block_text
                        else:
                            chunk_text += "\n" + block_text if chunk_text else block_text
                            
                if chunk_text:
                    chunk_id = str(uuid.uuid4())
                    c.execute('''
                        INSERT INTO documents (text, chunk_id, source_name, page_number, source_type, account_id, customer_scope, is_deprecated, effective_from)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        chunk_text, chunk_id, f, page_num + 1, meta['source_type'], 
                        meta['account_id'], meta['customer_scope'], meta['is_deprecated'], None
                    ))
            doc.close()

    print("Ingesting Excel data...")
    excel_path = next(os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.endswith('.xlsx'))
    accounts_df = pd.read_excel(excel_path, sheet_name='accounts')
    orders_df = pd.read_excel(excel_path, sheet_name='orders')
    tickets_df = pd.read_excel(excel_path, sheet_name='tickets')
    
    accounts_df.to_sql('accounts', conn, if_exists='append', index=False)
    orders_df.to_sql('orders', conn, if_exists='append', index=False)
    tickets_df.to_sql('tickets', conn, if_exists='append', index=False)

    conn.commit()
    conn.close()

    print("Re-hashing source files...")
    post_hashes = get_source_hashes()
    
    if pre_hashes == post_hashes:
        print("SUCCESS: Source files unchanged (hashes matched).")
    else:
        print("WARNING: Source files changed during ingestion.")
        raise Exception("Source files were mutated!")

if __name__ == '__main__':
    ingest()
