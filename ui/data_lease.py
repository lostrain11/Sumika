"""Process-lifetime single writer for bridge personal data, independent of port."""
from pathlib import Path


class DataLease:
    def __init__(self, directory, *, filename='sumika-bridge.lock'):
        if filename not in ('sumika-bridge.lock', 'sumika-instance.lock'):
            raise ValueError('unsupported ownership lock')
        self.directory = Path(directory).resolve()
        self.filename = filename
        self.file = None

    def acquire(self):
        import msvcrt
        self.directory.mkdir(parents=True, exist_ok=True)
        handle = (self.directory/self.filename).open('a+b')
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except BaseException:
            handle.close()
            raise
        self.file = handle
        return self

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None
