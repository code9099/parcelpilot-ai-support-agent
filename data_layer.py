import sqlite3
from typing import NamedTuple, List, Dict, Any, Optional
import db

class Session(NamedTuple):
    role: str
    account_id: Optional[str]

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def query_data(session: Session, query_type: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Whitelist query types to prevent arbitrary SQL
    ALLOWED_QUERIES = {
        'orders': ['order_id', 'status', 'carrier', 'account_id'],
        'tickets': ['ticket_id', 'status', 'account_id'],
        'accounts': ['account_id', 'plan', 'status'],
        'sla': [],
        'account_summary': []
    }
    
    if query_type not in ALLOWED_QUERIES:
        raise ValueError(f"Invalid query_type: {query_type}")

    conn = db.get_connection()
    conn.row_factory = dict_factory
    c = conn.cursor()

    if query_type in ['orders', 'tickets', 'accounts']:
        base_query = f"SELECT * FROM {query_type}"
        where_clauses = []
        sql_params = []
        allowed_params = ALLOWED_QUERIES[query_type]

        if session.role == 'customer':
            where_clauses.append("account_id = ?")
            sql_params.append(session.account_id)
        else:
            if session.role != 'internal':
                raise ValueError("Unauthorized role")

        for k, v in params.items():
            if k not in allowed_params:
                continue # Safely ignore unallowed parameters
                
            if k == 'account_id' and session.role == 'customer':
                continue # Customer account_id already enforced

            where_clauses.append(f"{k} = ?")
            sql_params.append(v)
            
        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
            
        c.execute(base_query, sql_params)
        results = c.fetchall()
        conn.close()
        return results

    conn.close()
    return []

def search_documents(session: Session, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    conn.row_factory = dict_factory
    c = conn.cursor()

    sql_query = """
        SELECT chunk_id, text, source_name, page_number, source_type, account_id, customer_scope, is_deprecated, effective_from 
        FROM documents 
        WHERE documents MATCH ?
    """
    
    if session.role == 'customer':
        sql_query += " AND (account_id IS NULL OR account_id = ?)"
        c.execute(sql_query, (query, session.account_id))
    elif session.role == 'internal':
        c.execute(sql_query, (query,))
    else:
        conn.close()
        raise ValueError("Unauthorized role")
        
    results = c.fetchall()
    conn.close()
    
    return results[:top_k]
