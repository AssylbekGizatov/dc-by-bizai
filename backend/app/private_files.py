"""Restrict private runtime files with native permissions, without invoking a shell.

POSIX uses owner-only modes. Windows uses a protected DACL for the current
account, SYSTEM and local administrators; chmod alone does not secure NTFS.
Call immediately after creating a file and before writing private contents.
"""
from __future__ import annotations

import os
from pathlib import Path


def _restrict_windows(path: Path, *, directory: bool) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    security.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    token = wintypes.HANDLE()
    sid_string = wintypes.LPWSTR()
    descriptor = ctypes.c_void_p()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buffer = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise ctypes.WinError(ctypes.get_last_error())
        inheritance = "OICI" if directory else ""
        dacl = "D:P" + "".join(f"(A;{inheritance};FA;;;{principal})" for principal in (sid_string.value, "SY", "BA"))
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(dacl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not security.SetFileSecurityW(str(path), 0x80000004, descriptor):  # protected DACL
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_string:
            kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def restrict_private_file(path: str | Path) -> None:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("Private files must not be symbolic links")
    if os.name == "nt":
        _restrict_windows(target.resolve(), directory=False)
    else:
        os.chmod(target, 0o600)


def restrict_private_directory(path: str | Path) -> None:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("Private directories must not be symbolic links")
    if os.name == "nt":
        _restrict_windows(target.resolve(), directory=True)
    else:
        os.chmod(target, 0o700)
