"""
Memory Manager - SQLite 작업 로그/피드백 + ChromaDB 투자 원칙/성향 (RAG)
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
    """메모리 관리자 - 작업 로그, 피드백, 투자 원칙, 사용자 성향 저장"""
    
    def __init__(self, db_path: Optional[str] = None, vector_store_path: Optional[str] = None):
        # 환경 변수 또는 기본값 사용
        self.db_path = db_path or os.getenv("DB_PATH", "shared/database.db")
        self.vector_store_path = vector_store_path or os.getenv("VECTOR_STORE_PATH", "manager/vector_store")
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
                task_type TEXT,
                status TEXT NOT NULL,
                input_data TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 사용자 피드백 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                content TEXT NOT NULL,
                rating INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _init_chroma(self):
        """ChromaDB 초기화"""
        if CHROMADB_AVAILABLE:
            os.makedirs(self.vector_store_path, exist_ok=True)
            # 최신 ChromaDB: PersistentClient 사용
            from chromadb import PersistentClient
            self.chroma_client = PersistentClient(path=self.vector_store_path)
            
            # 투자 원칙 컬렉션
            self.principles_collection = self.chroma_client.get_or_create_collection("investment_principles")
            # 사용자 성향 컬렉션
            self.user_profile_collection = self.chroma_client.get_or_create_collection("user_profile")
        else:
            self.chroma_client = None
            self.principles_collection = None
            self.user_profile_collection = None
    
    # ==================== SQLite: 작업 로그 ====================
    def save_log(self, task_id: str, task_type: str, status: str, 
                 input_data: Optional[Dict[str, Any]] = None, 
                 result: Optional[Dict[str, Any]] = None) -> bool:
        """
        작업 로그 저장
        
        Args:
            task_id: 작업 ID
            task_type: 작업 유형 (e.g., "market_analysis", "recommendation")
            status: 상태 ("pending", "processing", "completed", "failed")
            input_data: 입력 데이터
            result: 결과 데이터
        
        Returns:
            성공 여부
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO task_logs (task_id, task_type, status, input_data, result, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, task_type, status, 
                  json.dumps(input_data) if input_data else None,
                  json.dumps(result) if result else None,
                  datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving log: {e}")
            return False
    
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
                "task_type": row[2],
                "status": row[3],
                "input_data": json.loads(row[4]) if row[4] else None,
                "result": json.loads(row[5]) if row[5] else None,
                "created_at": row[6],
                "updated_at": row[7]
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
        """, (status, json.dumps(result) if result else None, datetime.now().isoformat(), task_id))
        
        conn.commit()
        conn.close()
    
    def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """최근 작업 목록 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT task_id, task_type, status, created_at, updated_at
            FROM task_logs
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {"task_id": row[0], "task_type": row[1], "status": row[2], 
             "created_at": row[3], "updated_at": row[4]}
            for row in rows
        ]
    
    # ==================== SQLite: 사용자 피드백 ====================
    def save_feedback(self, task_id: str, feedback_type: str, content: str, 
                      rating: Optional[int] = None) -> bool:
        """
        사용자 피드백 저장
        
        Args:
            task_id: 작업 ID
            feedback_type: 피드백 유형 ("correction", "approval", "preference", "complaint")
            content: 피드백 내용
            rating: 평점 (1-5)
        
        Returns:
            성공 여부
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO user_feedback (task_id, feedback_type, content, rating)
                VALUES (?, ?, ?, ?)
            """, (task_id, feedback_type, content, rating))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving feedback: {e}")
            return False
    
    def get_feedback_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """작업에 대한 피드백 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, feedback_type, content, rating, created_at
            FROM user_feedback
            WHERE task_id = ?
            ORDER BY created_at DESC
        """, (task_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {"id": row[0], "feedback_type": row[1], "content": row[2], 
             "rating": row[3], "created_at": row[4]}
            for row in rows
        ]
    
    def get_all_feedback(self, limit: int = 50) -> List[Dict[str, Any]]:
        """모든 피드백 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, task_id, feedback_type, content, rating, created_at
            FROM user_feedback
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {"id": row[0], "task_id": row[1], "feedback_type": row[2], 
             "content": row[3], "rating": row[4], "created_at": row[5]}
            for row in rows
        ]
    
    # ==================== ChromaDB: 투자 원칙 ====================
    def save_principle(self, principle_id: str, content: str, 
                       category: str = "general", 
                       metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        투자 원칙 저장 (RAG용 벡터)
        
        Args:
            principle_id: 원칙 ID
            content: 원칙 내용 (문서 텍스트)
            category: 카테고리 ("risk", "strategy", "asset_allocation", etc.)
            metadata: 추가 메타데이터
        
        Returns:
            성공 여부
        """
        if not self.principles_collection:
            print("ChromaDB not available")
            return False
        
        try:
            meta = metadata or {}
            meta["category"] = category
            meta["created_at"] = datetime.now().isoformat()
            
            self.principles_collection.add(
                documents=[content],
                ids=[principle_id],
                metadatas=[meta]
            )
            return True
        except Exception as e:
            print(f"Error saving principle: {e}")
            return False
    
    def get_relevant_principles(self, query: str, n_results: int = 5, 
                                category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        관련 투자 원칙 검색 (RAG)
        
        Args:
            query: 검색 쿼리
            n_results: 반환할 결과 수
            category: 필터링할 카테고리
        
        Returns:
            관련 원칙 목록
        """
        if not self.principles_collection:
            return []
        
        try:
            where = {"category": category} if category else None
            
            results = self.principles_collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where
            )
            
            # 결과 파싱
            if results and results.get("ids") and results["ids"][0]:
                return [
                    {
                        "id": results["ids"][0][i],
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else None
                    }
                    for i in range(len(results["ids"][0]))
                ]
            return []
        except Exception as e:
            print(f"Error searching principles: {e}")
            return []
    
    def get_all_principles(self) -> List[Dict[str, Any]]:
        """모든 투자 원칙 조회"""
        if not self.principles_collection:
            return []
        
        try:
            results = self.principles_collection.get()
            if results and results.get("ids"):
                return [
                    {
                        "id": results["ids"][i],
                        "content": results["documents"][i],
                        "metadata": results["metadatas"][i]
                    }
                    for i in range(len(results["ids"]))
                ]
            return []
        except Exception as e:
            print(f"Error getting principles: {e}")
            return []
    
    def delete_principle(self, principle_id: str) -> bool:
        """투자 원칙 삭제"""
        if not self.principles_collection:
            return False
        
        try:
            self.principles_collection.delete(ids=[principle_id])
            return True
        except Exception as e:
            print(f"Error deleting principle: {e}")
            return False
    
    # ==================== ChromaDB: 사용자 성향 ====================
    def save_user_profile(self, user_id: str, profile_text: str, 
                          traits: Optional[Dict[str, Any]] = None) -> bool:
        """
        사용자 성향 저장
        
        Args:
            user_id: 사용자 ID
            profile_text: 성향 설명 텍스트
            traits: 특성 딕셔너리 (risk_tolerance, investment_style, etc.)
        
        Returns:
            성공 여부
        """
        if not self.user_profile_collection:
            print("ChromaDB not available")
            return False
        
        try:
            meta = traits or {}
            meta["user_id"] = user_id
            meta["updated_at"] = datetime.now().isoformat()
            
            self.user_profile_collection.add(
                documents=[profile_text],
                ids=[user_id],
                metadatas=[meta]
            )
            return True
        except Exception as e:
            print(f"Error saving user profile: {e}")
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """사용자 성향 조회"""
        if not self.user_profile_collection:
            return None
        
        try:
            results = self.user_profile_collection.get(ids=[user_id])
            if results and results.get("ids") and results["ids"]:
                return {
                    "id": results["ids"][0],
                    "profile": results["documents"][0],
                    "traits": results["metadatas"][0]
                }
            return None
        except Exception as e:
            print(f"Error getting user profile: {e}")
            return None
    
    def search_similar_profiles(self, query: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """유사 사용자 성향 검색"""
        if not self.user_profile_collection:
            return []
        
        try:
            results = self.user_profile_collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            if results and results.get("ids") and results["ids"][0]:
                return [
                    {
                        "id": results["ids"][0][i],
                        "profile": results["documents"][0][i],
                        "traits": results["metadatas"][0][i]
                    }
                    for i in range(len(results["ids"][0]))
                ]
            return []
        except Exception as e:
            print(f"Error searching profiles: {e}")
            return []


if __name__ == "__main__":
    # 테스트
    manager = MemoryManager()
    
    # 작업 로그 저장
    manager.save_log("task_001", "market_analysis", "completed", 
                     {"symbol": "AAPL"}, {"trend": "upward"})
    
    # 피드백 저장
    manager.save_feedback("task_001", "approval", "좋은 분석이었습니다", 5)
    
    # 투자 원칙 저장
    manager.save_principle(
        "principle_001",
        "위험 노출은 포트폴리오의 20%를 초과하지 않는다",
        "risk",
        {"min_age": 30, "priority": "high"}
    )
    
    # 관련 원칙 검색
    principles = manager.get_relevant_principles("위험 관리 원칙")
    print("Relevant principles:", principles)
    
    # 사용자 성향 저장
    manager.save_user_profile(
        "user_001",
        "위험을 싫어하는 보수적 투자자, 장기 보유 선호",
        {"risk_tolerance": "low", "investment_horizon": "long"}
    )