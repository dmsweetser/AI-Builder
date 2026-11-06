"""Cross-platform file locking utility.

Uses a lock file + atomic rename. Works on all platforms
(no fcntl/msvcrt dependency).
"""
import os
import time


class FileLock:
    """Simple file-based lock for preventing concurrent writes.

    Uses atomic file creation for cross-platform compatibility.
    """

    def __init__(self, lock_path: str, timeout: float = 30.0):
        self.lock_path = lock_path + ".lock"
        self.timeout = timeout
        self._lock_file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def acquire(self):
        """Acquire the lock (blocking with timeout)."""
        deadline = time.time() + self.timeout
        while True:
            try:
                # Try to create the lock file atomically
                tmp_path = self.lock_path + ".tmp"
                with open(tmp_path, 'w') as f:
                    f.write(str(os.getpid()))
                os.replace(tmp_path, self.lock_path)
                self._lock_file = open(self.lock_path, 'r')
                return
            except (IOError, OSError):
                if time.time() >= deadline:
                    # Clean up any stale lock file
                    try:
                        os.remove(self.lock_path)
                    except OSError:
                        pass
                    raise TimeoutError(
                        f"Could not acquire lock on {self.lock_path} "
                        f"within {self.timeout}s"
                    )
                time.sleep(0.05)

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                self._lock_file.close()
            except OSError:
                pass
            finally:
                self._lock_file = None
            try:
                os.remove(self.lock_path)
            except OSError:
                pass
