"""Scheduled, idempotent cleanup of opted-in expired trash and queued files."""
from main import get_connection
from trash_management import retention_cleanup, drain_file_queue

if __name__ == "__main__":
    expired = retention_cleanup(get_connection)
    queue = drain_file_queue(get_connection, limit=5000)
    print(f"Expired trash entries deleted: {expired}; file queue: {queue}")
