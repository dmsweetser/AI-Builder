"""Cross-platform file locking utility.

Uses fcntl on Unix and msvcrt on Windows.
"""
import os
import time
import sys


class FileLock:
    """Simple file-based lock for preventing concurrent writes.

    Works on both Unix (fcntl) and Windows (msvcrt).
    """

    def __init__(self, lock_path: str, timeout: float = 30.0):
        self.lock_path = lock_path + ".lock"
        self.timeout = timeout
        self._lock_file = None
        self._is_windows = sys.platform == "win32"

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def acquire(self):
        """Acquire the lock (blocking with timeout)."""
        self._lock_file = open(self.lock_path, 'w')
        deadline = time.time() + self.timeout
        while True:
            try:
                if self._is_windows:
                    import msvcrt
                    msvcrt.locking(
                        self._lock_file.fileno(),
                        msvcrt.LK_NBLCK,
                        1,
                    )
                else:
                    import fcntl
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (IOError, OSError):
                if time.time() >= deadline:
                    self._lock_file.close()
                    self._lock_file = None
                    raise TimeoutError(
                        f"Could not acquire lock on {self.lock_path} "
                        f"within {self.timeout}s"
                    )
                time.sleep(0.05)

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                if self._is_windows:
                    import msvcrt
                    msvcrt.locking(
                        self._lock_file.fileno(),
                        msvcrt.LK_UNLCK,
                        1,
                    )
                else:
                    import fcntl
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                try:
                    self._lock_file.close()
                except OSError:
                    pass
                self._lock_file = None
