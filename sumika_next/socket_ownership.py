"""Windows listener PID lookup without spawning PowerShell/WMI.

Query both address families on every check; errors never mean an empty table.
This is an observation, not a retained authorization or a socket reservation.
"""
import ctypes
import os
import socket


def listener_pids(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid listener port')
    if os.name != 'nt':
        raise OSError('Windows TCP ownership provider unavailable')
    api = ctypes.WinDLL('iphlpapi', use_last_error=True).GetExtendedTcpTable
    dword = ctypes.c_uint32
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(dword), ctypes.c_int,
                    dword, ctypes.c_int, dword]
    api.restype = dword
    owners = set()
    for family, row_size, port_offset, pid_offset in (
            (socket.AF_INET, 24, 8, 20), (socket.AF_INET6, 56, 20, 52)):
        size = dword(0)
        result = api(None, ctypes.byref(size), False, family, 3, 0)
        if result not in (0, 122):
            raise OSError(result, 'cannot size TCP listener table')
        for _ in range(4):
            capacity = size.value
            if not 4 <= capacity <= 16 * 1024 * 1024:
                raise OSError('invalid TCP table size')
            buffer = ctypes.create_string_buffer(capacity)
            result = api(buffer, ctypes.byref(size), False, family, 3, 0)
            if result == 122:
                continue
            if result:
                raise OSError(result, 'cannot read TCP listener table')
            raw = buffer.raw
            count = int.from_bytes(raw[:4], 'little')
            if size.value > capacity or 4 + count * row_size > min(size.value, capacity):
                raise OSError('truncated TCP listener table')
            for index in range(count):
                row = raw[4 + index * row_size:4 + (index + 1) * row_size]
                if int.from_bytes(row[port_offset:port_offset + 2], 'big') == port:
                    owners.add(int.from_bytes(row[pid_offset:pid_offset + 4], 'little'))
            break
        else:
            raise OSError('TCP listener table did not stabilize')
    return owners
