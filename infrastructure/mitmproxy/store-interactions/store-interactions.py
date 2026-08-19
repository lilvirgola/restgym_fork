import sqlite3
import os
import json

class StoreInteractions:
    conn = None
    cursor = None
    count = 0

    def __init__(self):
        self.conn = self.open_sqlite()
        self.cursor = self.conn.cursor()
        self.init_sqlite()

    def open_sqlite(self):
        # Ensure the directory exists before connecting
        db_path = f"results/{os.environ.get('API', 'default')}/{os.environ.get('TOOL', 'default')}/{os.environ.get('RUN', 'default')}/results.db"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return sqlite3.connect(db_path)
    
    def init_sqlite(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS interactions (
            id integer PRIMARY KEY, 
            request_method text, request_path text, request_headers text, request_content text, request_timestamp real, 
            response_status_code integer, response_headers text, response_content text, response_timestamp real,
            mutant_id text, mutant_operator text, mutant_taxonomy text, is_killed integer
        )''')
        self.conn.commit()
    
    def response(self, flow):
        mutant = flow.metadata.get("active_mutant") if hasattr(flow, "metadata") else None
        
        m_id = mutant.get("id") if mutant else None
        m_op = mutant.get("operator") if mutant else None
        m_tax = mutant.get("taxonomy") if mutant else None

        # FIX: Safely serialize headers
        req_headers = "\r\n".join(f"{k}: {v}" for k, v in flow.request.headers.items())
        req_content = flow.request.content.decode('utf-8', errors='replace') if flow.request.content else ""
        
        res_headers = ""
        res_content = ""
        res_status = None
        res_time = None
        
        if flow.response:
            res_headers = "\r\n".join(f"{k}: {v}" for k, v in flow.response.headers.items())
            res_content = flow.response.content.decode('utf-8', errors='replace') if flow.response.content else ""
            res_status = flow.response.status_code
            res_time = flow.response.timestamp_start

        self.cursor.execute('''
            INSERT INTO interactions (
                request_method, request_path, request_headers, request_content, request_timestamp, 
                response_status_code, response_headers, response_content, response_timestamp,
                mutant_id, mutant_operator, mutant_taxonomy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            flow.request.method, flow.request.path, req_headers, req_content, flow.request.timestamp_start, 
            res_status, res_headers, res_content, res_time,
            m_id, m_op, m_tax
        ))
        
        self.count += 1
        if self.count % 100 == 0:
            self.conn.commit()

    def done(self):
        if self.conn:
            self.conn.commit()
            self.conn.close()

addons = [StoreInteractions()]