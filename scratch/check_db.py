from manager.memory_manager import MemoryManager
import logging

logging.basicConfig(level=logging.INFO)
memory = MemoryManager()

def check_stats():
    print("--- Memory Stats ---")
    if hasattr(memory, 'autonomous_logs_collection'):
        count = memory.autonomous_logs_collection.count()
        print(f"Autonomous Logs: {count} items")
        if count > 0:
            logs = memory.get_autonomous_logs(limit=5)
            for log in logs:
                print(f"- [{log['timestamp']}] {log['id']} (Length: {len(log['content'])})")
    
    if hasattr(memory, 'learnings_collection'):
        print(f"Learnings: {memory.learnings_collection.count()} items")
    
    if hasattr(memory, 'knowledge_notes_collection'):
        print(f"Knowledge Notes: {memory.knowledge_notes_collection.count()} items")

if __name__ == "__main__":
    check_stats()
