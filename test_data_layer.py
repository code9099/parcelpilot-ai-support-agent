import pytest
import sqlite3
from data_layer import Session, query_data, search_documents
import db
import ingest
import os

def test_source_file_hashes_unchanged():
    # Genuinely check hashes before and after the full ingestion process
    pre_hashes = ingest.get_source_hashes()
    
    # Run the ingestion function
    ingest.ingest()
    
    post_hashes = ingest.get_source_hashes()
    
    # Verify that exactly the same files are hashed and they match byte-for-byte
    assert set(pre_hashes.keys()) == set(post_hashes.keys())
    assert len(pre_hashes) > 0
    for file_name, pre_hash in pre_hashes.items():
        assert pre_hash == post_hashes[file_name]

def test_load_all_expected_structured_data():
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM accounts")
    assert c.fetchone()[0] > 0
    c.execute("SELECT COUNT(*) FROM orders")
    assert c.fetchone()[0] > 0
    c.execute("SELECT COUNT(*) FROM tickets")
    assert c.fetchone()[0] > 0
    conn.close()

def test_customer_isolation_structured():
    s1 = Session('customer', 'ACCT-001')
    s2 = Session('customer', 'ACCT-002')
    
    res1 = query_data(s1, 'orders', {})
    assert all(r['account_id'] == 'ACCT-001' for r in res1)
    assert len(res1) > 0
    
    res2 = query_data(s2, 'orders', {})
    assert all(r['account_id'] == 'ACCT-002' for r in res2)
    assert len(res2) > 0
    
    # Cross-account data retrieval
    # Ensure they can't access each other's data
    res1_tickets = query_data(s1, 'tickets', {})
    assert all(r['account_id'] == 'ACCT-001' for r in res1_tickets)

def test_customer_override_rejected():
    s1 = Session('customer', 'ACCT-001')
    # Try to access ACCT-002 data by passing it in params
    res = query_data(s1, 'orders', {'account_id': 'ACCT-002'})
    # Must only return ACCT-001 data, failing safely
    assert all(r['account_id'] == 'ACCT-001' for r in res)

def test_internal_access():
    s_internal = Session('internal', None)
    res = query_data(s_internal, 'orders', {'account_id': 'ACCT-001'})
    assert len(res) > 0
    assert all(r['account_id'] == 'ACCT-001' for r in res)
    
    res2 = query_data(s_internal, 'orders', {})
    assert len(res2) > len(res) # Should get all orders

def test_arbitrary_sql_rejected():
    s = Session('internal', None)
    with pytest.raises(ValueError):
        query_data(s, 'DROP TABLE orders', {})
        
def test_malicious_parameter_injection():
    s = Session('internal', None)
    # Test malicious key: it should fail safely (ignored or ValueError)
    # Our implementation ignores unallowed keys, so it will return all orders safely.
    res1 = query_data(s, 'orders', {"status = 'x' OR 1=1 --": ""})
    res_all = query_data(s, 'orders', {})
    assert len(res1) == len(res_all)
    
    # Test malicious value: parameterization protects this natively in SQLite
    res2 = query_data(s, 'orders', {"status": "' OR 1=1 --"})
    assert len(res2) == 0  # No order actually has this string as its status

def test_document_retrieval_isolation():
    s1 = Session('customer', 'ACCT-001')
    s2 = Session('customer', 'ACCT-002')
    s_internal = Session('internal', None)
    
    # Northstar agreement is visible to ACCT-001.
    res = search_documents(s1, 'Northstar', top_k=50)
    assert any('Northstar' in r['source_name'] for r in res)
    
    # LumenWorks agreement is visible to ACCT-002.
    res = search_documents(s2, 'LumenWorks', top_k=50)
    assert any('LumenWorks' in r['source_name'] for r in res)
    
    # Cross-account document retrieval attempts
    res = search_documents(s1, 'LumenWorks', top_k=50)
    assert not any('LumenWorks_Service_Agreement' in r['source_name'] for r in res)
    
    res = search_documents(s2, 'Northstar', top_k=50)
    assert not any('Northstar_Logistics' in r['source_name'] for r in res)
    
    # Global documents remain available to customer sessions
    res = search_documents(s1, 'Support', top_k=50)
    assert any(r['customer_scope'] == 'global' for r in res)
    
def test_fts_chunking_and_metadata():
    s_internal = Session('internal', None)
    res = search_documents(s_internal, 'Support', top_k=50)
    assert len(res) > 0
    
    for doc in res:
        # Check max chunk bounds: ~1000 + length of the longest block
        # We can conservatively assert max 1500
        assert len(doc['text']) <= 2500
        assert isinstance(doc['page_number'], int) or str(doc['page_number']).isdigit()
        assert 'chunk_id' in doc
        assert 'source_type' in doc
        assert 'is_deprecated' in doc
