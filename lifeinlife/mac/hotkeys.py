"""System-wide Ctrl+Shift shortcuts via Carbon's RegisterEventHotKey.
Unlike an NSEvent global monitor, this needs no Accessibility permission."""
import ctypes


def _fourcc(code):
    return int.from_bytes(code.encode(), "big")


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HOTKEY_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class CarbonHotkeys:
    """`keycodes` maps macOS key codes to action names; `on_action(name)` is called
    (on the main thread, while SDL pumps events) when Ctrl+Shift+<key> is pressed anywhere."""

    CONTROL, SHIFT = 0x1000, 0x0200  # Carbon modifier bits (controlKey, shiftKey)

    def __init__(self, keycodes, on_action):
        c = self.carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, _HOTKEY_HANDLER, ctypes.c_ulong,
                                          ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.InstallEventHandler.restype = ctypes.c_int32
        c.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                                        ctypes.c_void_p]
        c.GetEventParameter.restype = ctypes.c_int32

        self.target = c.GetApplicationEventTarget()
        self.signature = _fourcc("LiLf")
        self.keycodes = list(keycodes)
        self.actions = [keycodes[k] for k in self.keycodes]
        self.refs = []

        def handler(_call, event, _data):
            hk = _EventHotKeyID()
            if c.GetEventParameter(event, _fourcc("----"), _fourcc("hkid"), None,
                                   ctypes.sizeof(hk), None, ctypes.byref(hk)) == 0:
                if hk.signature == self.signature and hk.id < len(self.actions):
                    on_action(self.actions[hk.id])
            return 0

        self._handler = _HOTKEY_HANDLER(handler)  # keep a reference so it isn't freed
        spec = _EventTypeSpec(_fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
        self.handler_ref = ctypes.c_void_p()
        if c.InstallEventHandler(self.target, self._handler, 1, ctypes.byref(spec), None,
                                 ctypes.byref(self.handler_ref)) != 0:
            raise OSError("InstallEventHandler failed")

    def register(self):
        if self.refs:
            return
        for i, code in enumerate(self.keycodes):
            ref = ctypes.c_void_p()
            if self.carbon.RegisterEventHotKey(code, self.CONTROL | self.SHIFT,
                                               _EventHotKeyID(self.signature, i), self.target,
                                               0, ctypes.byref(ref)) == 0:
                self.refs.append(ref)

    def unregister(self):
        for ref in self.refs:
            self.carbon.UnregisterEventHotKey(ref)
        self.refs = []

    def close(self):
        self.unregister()
        if self.handler_ref:
            self.carbon.RemoveEventHandler(self.handler_ref)
            self.handler_ref = ctypes.c_void_p()
