from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from dataclasses import dataclass

JobHandle = wt.HANDLE
ProcessHandle = wt.HANDLE

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None

if KERNEL32 is not None:
    KERNEL32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    KERNEL32.CreateJobObjectW.restype = wt.HANDLE
    KERNEL32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    KERNEL32.SetInformationJobObject.restype = wt.BOOL
    KERNEL32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    KERNEL32.OpenProcess.restype = wt.HANDLE
    KERNEL32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    KERNEL32.AssignProcessToJobObject.restype = wt.BOOL
    KERNEL32.CloseHandle.argtypes = [wt.HANDLE]
    KERNEL32.CloseHandle.restype = wt.BOOL

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x2
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
JobObjectExtendedLimitInformation = 9
PROCESS_ALL_ACCESS = 0x1F0FFF
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


@dataclass
class JobLimits:
    memory_bytes: int = 1024 * 1024 * 1024
    cpu_100ns: int = 30 * 10_000_000
    active_process_limit: int = 8


class JobObject:
    def __init__(self, limits: JobLimits | None = None) -> None:
        if sys.platform != "win32" or KERNEL32 is None:
            self.handle = None
            return
        self.handle = KERNEL32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObjectW failed")
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        cfg = limits or JobLimits()
        info.BasicLimitInformation.LimitFlags = flags | JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_PROCESS_TIME
        info.BasicLimitInformation.ActiveProcessLimit = cfg.active_process_limit
        info.BasicLimitInformation.PerProcessUserTimeLimit = cfg.cpu_100ns
        info.JobMemoryLimit = cfg.memory_bytes
        ok = KERNEL32.SetInformationJobObject(
            self.handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            fallback = KERNEL32.SetInformationJobObject(
                self.handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not fallback:
                KERNEL32.CloseHandle(self.handle)
                self.handle = None

    def assign(self, pid: int) -> None:
        if not self.handle:
            return
        proc = KERNEL32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not proc:
            raise OSError("OpenProcess failed")
        try:
            if not KERNEL32.AssignProcessToJobObject(self.handle, proc):
                raise OSError("AssignProcessToJobObject failed")
        finally:
            KERNEL32.CloseHandle(proc)

    def close(self) -> None:
        if self.handle and KERNEL32 is not None:
            KERNEL32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "JobObject":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
