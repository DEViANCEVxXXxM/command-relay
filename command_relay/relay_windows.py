# SPDX-License-Identifier: Apache-2.0
"""Per-window Windows chrome; never modifies system preferences."""
import sys


def colorref(rgb):
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


def apply_neutral_chrome(hwnd, theme="dark"):
    """Best effort on Windows 11. Unsupported attributes leave native defaults."""
    if sys.platform != 'win32' or not hwnd:
        return {}
    import ctypes
    from ctypes import wintypes
    try:
        setter = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        setter.restype = ctypes.c_long
        light = theme == 'light'
        values = ((20, int(not light)), (34, colorref((160, 172, 186) if light else (66, 73, 81))),
                  (35, colorref((243, 245, 247) if light else (24, 26, 30))),
                  (36, colorref((34, 43, 54) if light else (226, 229, 233))))
        result = {}
        for attr, value in values:
            data = wintypes.DWORD(value)
            result[attr] = setter(hwnd, attr, ctypes.byref(data), ctypes.sizeof(data))
        return result
    except (OSError, AttributeError, ValueError):
        return {}


APP_USER_MODEL_ID = 'CommandRelay.QtWorkbench'

def set_app_identity():
    """Set the process taskbar identity before creating any windows; best effort."""
    if sys.platform != 'win32':
        return False
    import ctypes
    try:
        setter = ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        return setter(APP_USER_MODEL_ID) == 0
    except (OSError, AttributeError, ValueError):
        return False


# The helper executes no reviewed code until the parent has attached it to a job.
# -I -S prevents project-local imports and Python site startup hooks.
_GATE_HELPER = '''import sys, subprocess
if sys.stdin.buffer.read(1) != b'R':
    sys.exit(125)
sys.exit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))
'''


class _WindowsJob:
    """Non-inheritable job handle, kill on close, no breakaway permission."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('PerProcessUserTimeLimit', c.c_longlong), ('PerJobUserTimeLimit', c.c_longlong),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', c.c_size_t),
                        ('MaximumWorkingSetSize', c.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', c.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(n, c.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount',
                        'ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(c.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO)] + [(n,c.c_size_t) for n in
                        ('ProcessMemoryLimit','JobMemoryLimit','PeakProcessMemoryUsed','PeakJobMemoryUsed')]
        class Accounting(c.Structure):
            _fields_ = [(n,c.c_longlong) for n in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')] + [(n,w.DWORD) for n in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]
        self.c = c; self.accounting = Accounting
        k = c.WinDLL('kernel32', use_last_error=True)
        def bind(name, args, result=w.BOOL):
            fn = getattr(k,name); fn.argtypes=args; fn.restype=result; return fn
        create = bind('CreateJobObjectW', [c.c_void_p,w.LPCWSTR], w.HANDLE)
        self._close = bind('CloseHandle',[w.HANDLE])
        self._assign = bind('AssignProcessToJobObject',[w.HANDLE,w.HANDLE])
        self._query = bind('QueryInformationJobObject',[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p])
        self._terminate = bind('TerminateJobObject',[w.HANDLE,w.UINT])
        set_info = bind('SetInformationJobObject',[w.HANDLE,c.c_int,c.c_void_p,w.DWORD])
        self.handle = create(None,None)
        if not self.handle: raise c.WinError(c.get_last_error())
        limits = Extended(); limits.BasicLimitInformation.LimitFlags = 0x2000 # KILL_ON_JOB_CLOSE
        if not set_info(self.handle,9,c.byref(limits),c.sizeof(limits)):
            err=c.WinError(c.get_last_error()); self.close(); raise err

    def assign(self, process):
        # CPython's Windows Popen owns this exact process handle; no PID lookup/reuse.
        if not self._assign(self.handle, int(process._handle)):
            raise self.c.WinError(self.c.get_last_error())

    def active(self):
        data=self.accounting()
        if not self._query(self.handle,1,self.c.byref(data),self.c.sizeof(data),None):
            raise self.c.WinError(self.c.get_last_error())
        return data.ActiveProcesses

    def terminate(self):
        if not self._terminate(self.handle, 1):
            raise self.c.WinError(self.c.get_last_error())

    def close(self):
        if self.handle:
            if not self._close(self.handle): raise self.c.WinError(self.c.get_last_error())
            self.handle=None


class _BoundedPipe:
    """Drain concurrently, emit only on controller thread. Retain max+1 bytes
    so the dispatch layer detects overflow; drain/discard the rest to EOF."""
    def __init__(self, stream, limit):
        import threading
        self.stream=stream; self.remaining=limit+1; self.buffer=bytearray()
        self.lock=threading.Lock(); self.done=False; self.error=False
        self.thread=threading.Thread(target=self._read,daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while True:
                chunk=self.stream.read(65536)
                if not chunk: break
                with self.lock:
                    count=min(len(chunk),self.remaining)
                    self.buffer.extend(chunk[:count]); self.remaining-=count
        except (OSError, ValueError):
            with self.lock: self.error=True
        finally:
            try: self.stream.close()
            finally:
                with self.lock: self.done=True

    def pump(self, emit):
        with self.lock:
            data=bytes(self.buffer); self.buffer.clear(); done=self.done; error=self.error
            if done: self.error=False
        if data: emit(data)
        # An unreadable pipe is not a complete UTF-8 report.
        if done and error: emit(b'\xff')
        return done


class WindowsPowerShellRun:
    """Internal backend for reviewed dispatch, not a sandbox or a GUI Run action.

    Controller calls poll/settled/cancel serially. Job membership and pipe EOF
    are required before completion. No taskkill fallback or uncontained launch.
    """
    def __init__(self, attempt, review, emit):
        import pathlib, subprocess, tempfile
        from .relay_core import sha, ExecutionDispatch
        if sys.platform != 'win32': raise OSError('Windows PowerShell backend requires Windows')
        if attempt.task_id != review.task_id or sha(review.prepared)!=attempt.prepared_sha256:
            raise ValueError('Reviewed attempt mismatch')
        review.verify_workspace()
        # Resolve trusted system directory from Windows API, not the task/PATH.
        import ctypes as c
        get_dir=c.WinDLL('kernel32',use_last_error=True).GetSystemDirectoryW
        get_dir.argtypes=[c.c_wchar_p,c.c_uint];get_dir.restype=c.c_uint
        buf=c.create_unicode_buffer(32768); n=get_dir(buf,len(buf))
        if not 0<n<len(buf): raise c.WinError(c.get_last_error())
        exe=pathlib.Path(buf.value)/'WindowsPowerShell'/'v1.0'/'powershell.exe'
        if not exe.is_file(): raise OSError('System PowerShell executable unavailable')
        self.attempt=attempt; self.emit=emit; self.process=None; self.pipe=None; self.closed=False
        self.temp=tempfile.TemporaryDirectory(prefix='relay-attempt-'); self.job=None
        try:
            script=pathlib.Path(self.temp.name)/'reviewed.ps1';script.write_bytes(review.prepared)
            self.job=_WindowsJob()
            self.process=subprocess.Popen([sys.executable,'-I','-S','-c',_GATE_HELPER,str(exe),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],
                cwd=review.workspace,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
            self.job.assign(self.process)
            self.pipe=_BoundedPipe(self.process.stdout,ExecutionDispatch.MAX_OUTPUT)
            review.verify_workspace()
            # Only now can the helper start PowerShell. Never change execution policy.
            if self.process.stdin.write(b'R')!=1: raise OSError('Launch gate failed')
            self.process.stdin.close()
        except BaseException:
            # No gate release on attach failure. On ambiguous errors kill the job
            # and preserve the dispatch slot; never claim a successful completion.
            if self.process is not None:
                try: self.process.stdin.close()
                except OSError: pass
                if self.process.poll() is None:
                    try: self.process.kill()
                    except OSError: pass
            if self.job is not None: self.job.close()
            if self.process is not None:
                self.process.wait(timeout=10)
                if self.pipe is None: self.process.stdout.close()
                else: self.pipe.thread.join(timeout=10)
            self.temp.cleanup()
            raise

    def poll(self):
        code=self.process.poll()
        if not self.closed: self.pipe.pump(self.emit)
        return code

    def settled(self, attempt, handle):
        if handle is not self or attempt!=self.attempt: return False
        if self.closed: return True
        if self.process.poll() is None or self.job.active()!=0: return False
        if not self.pipe.pump(self.emit): return False
        self.job.close(); self.temp.cleanup(); self.closed=True
        return True

    def cancel(self, attempt, handle):
        if handle is not self or attempt!=self.attempt or self.closed: raise ValueError('Wrong or completed attempt')
        self.job.terminate()
