"""
Memory Manager - ChromaDB (RAG) 및 SQLite 관리
"""
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import json

try:
    from chromadb import Client as ChromaClient
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class MemoryManager:
    """메모리 관리자"""
    
    def __init__(self, db_path: str = "shared/database.db", vector_store_path: str = "manager/vector_store"):
        self.db_path = db_path
        self.vector_store_path = vector_store_path
        self._init_sqlite()
        self._init_chroma()
    
    def _init_sqlite(self):
        """SQLite 초기화"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 작업 로그 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                input_data TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 컨텍스트 로그 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS context_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                context_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _init_chroma(self):
        """ChromaDB 초기화"""
        if CHROMADB_AVAILABLE:
            os.makedirs(self.vector_store_path, exist_ok=True)
            self.chroma_client = ChromaClient(persist_directory=self.vector_store_path)
            self.collection = self.chroma_client.get_or_create_collection("nexus_context")
        else:
            self.chroma_client = None
            self.collection = None
    
    # SQLite operations
    def log_task(self, task_id: str, status: str, input_data: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
        """작업 로깅"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO task_logs (task_id, status, input_data, result, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, status, json.dumps(input_data), json.dumps(result), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_task_log(self, task_id: str) -> Optional[Dict[str, Any]]:
        """작업 로그 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM task_logs WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "task_id": row[1],
                "status": row[2],
                "input_data": json.loads(row[3]) if row[3] else None,
                "result": json.loads(row[4]) if row[4] else None,
                "created_at": row[5],
                "updated_at": row[6]
            }
        return None
    
    def update_task_status(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None):
        """작업 상태 업데이트"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE task_logs 
            SET status = ?, result = ?, updated_at = ?
            WHERE task_id = ?
        """, (status, json.dumps(result), datetime.now().isoformat(), task_id))
        
        conn.commit()
        conn.close()
    
    def log_context(self, task_id: str, context_data: Dict[str, Any]):
        """컨텍스트 로깅"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO context_logs (task_id, context_data)
            VALUES (?, ?)
        """, (task_id, json.dumps(context_data)))
        
        conn.commit()
        conn.close()
    
    # ChromaDB operations
    def add_context_vector(self, task_id: str, text: str, metadata: Optional[Dict[str, Any]] = None):
        """컨텍스트 벡터 추가"""
        if self.collection:
            self.collection.add(
                documents=[text],
                ids=[task_id],
                metadatas=[metadata or {}]
            )
    
    def search_similar_context(self, query: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """유사 컨텍스트 검색"""
        if self.collection:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            return results
        return []
    
    def get_recent_contexts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """최근 컨텍스트 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT task_id, context_data, created_at 
            FROM context_logs 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {"task_id": row[0], "context_data": json.loads(row[1]), "created_at": row[2]}
            for row in rows
        ]


if __name__ == "__main__":
    # 테스트
    manager = MemoryManager()
    manager.log_task("test_001", "pending", {"test": "data"})
    print(manager.get_task_log("test_001"))