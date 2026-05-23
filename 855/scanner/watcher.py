"""文件监听器 — 用于 --watch 模式"""

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class SourceChangeHandler(FileSystemEventHandler):
    """处理文件变更事件，带防抖"""

    def __init__(self, callback, extensions: list[str], debounce: float = 2.0):
        super().__init__()
        self.callback = callback
        self.extensions = extensions
        self.debounce = debounce
        self._last_fire: dict[str, float] = {}
        self.logger = logging.getLogger("mimodoc.watcher")

    def on_modified(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._trigger(event.src_path)

    def on_created(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._trigger(event.src_path)

    def _matches(self, path: str) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def _trigger(self, path: str):
        now = time.monotonic()
        last = self._last_fire.get(path, 0)
        if now - last < self.debounce:
            return
        self._last_fire[path] = now
        self.logger.info("检测到变更: %s", path)
        self.callback([path])


class FileWatcher:
    """监听源目录并在变更时触发重新生成"""

    def __init__(self, paths: list[str], extensions: list[str],
                 callback, interval: float = 2.0):
        self.paths = paths
        self.extensions = extensions
        self.callback = callback
        self.interval = interval
        self.observer = Observer()
        self.logger = logging.getLogger("mimodoc.watcher")

    def start(self):
        handler = SourceChangeHandler(self.callback, self.extensions, debounce=self.interval)
        for p in self.paths:
            path = Path(p)
            if path.exists():
                self.observer.schedule(handler, str(path), recursive=True)
                self.logger.info("监听: %s", path)
        self.observer.start()
        self.logger.info("文件监听已启动 (debounce=%.1fs)", self.interval)

    def stop(self):
        self.observer.stop()
        self.observer.join()
        self.logger.info("文件监听已停止")

    def run_forever(self):
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
