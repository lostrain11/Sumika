"""Single managed writer per profile, with durable unknown-state fencing."""
import ctypes
import json
import os
import uuid
from pathlib import Path


def process_identity(pid):
    """Creation time distinguishes a reused PID; access failure is not absence."""
    if os.name != 'nt':
        raise OSError('process identity provider unavailable')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        error=ctypes.get_last_error()
        if error==87: return None
        raise OSError(error,'cannot inspect process identity')
    try:
        exit_code=wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code)):
            raise OSError(ctypes.get_last_error(),'cannot inspect exit status')
        if exit_code.value != 259: return None
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
            raise OSError(ctypes.get_last_error(),'cannot inspect creation time')
        return str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
    finally: kernel.CloseHandle(handle)


class ProfileLease:
    def __init__(self, home):
        self.home=Path(home).resolve()
        self.file=None
        self.record=self.home/'sumika-instance.json'
        self.instance_id=uuid.uuid4().hex

    def acquire(self):
        import msvcrt
        self.home.mkdir(parents=True,exist_ok=True)
        self.file=(self.home/'sumika-instance.lock').open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0: self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            prior=json.loads(self.record.read_text(encoding='utf8')) if self.record.exists() else {}
            if not isinstance(prior,dict):
                raise ValueError('invalid ownership record')
            if prior:
                if not isinstance(prior,dict) or prior.get('profile')!=str(self.home):
                    raise ValueError('invalid ownership record')
                pid=prior.get('pid')
                identity=prior.get('creation')
                if type(pid)!=int or not isinstance(identity,str):
                    raise ValueError('incomplete previous launch; manual inspection required')
                if process_identity(pid)==identity:
                    raise ValueError('previous managed process still alive; no new writer allowed')
            self._write({'instance_id':self.instance_id,'profile':str(self.home),'state':'starting'})
            return self
        except BaseException:
            self.file.close();self.file=None
            raise

    def bind(self, process):
        identity=process_identity(process.pid)
        if identity is None: raise ValueError('managed process disappeared before binding')
        self._write({'instance_id':self.instance_id,'profile':str(self.home),'state':'running',
                     'pid':process.pid,'creation':identity})

    def _write(self,value):
        temp=self.record.with_suffix('.tmp')
        with temp.open('w',encoding='utf8') as out:
            json.dump(value,out);out.flush();os.fsync(out.fileno())
        os.replace(temp,self.record)

    def release(self):
        if self.file is not None:
            self._write({})
            self.file.close();self.file=None
