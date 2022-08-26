# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\daemon\windows_signal.py
__doc__ = '\nCode taken from Stack Overflow Eryk Sun.\nhttps://stackoverflow.com/questions/35772001/how-to-handle-the-signal-in-python-on-windows-machine\n'
import os, signal, sys
if sys.platform != 'win32' and sys.platform != 'cygwin':
    kill = os.kill
else:
    import threading
    sigmap = {signal.SIGINT: signal.CTRL_C_EVENT, 
     signal.SIGBREAK: signal.CTRL_BREAK_EVENT}

    def kill(pid, signum):
        if signum in sigmap:
            if pid == os.getpid():
                pid = 0
        thread = threading.current_thread()
        handler = signal.getsignal(signum)
        if signum in sigmapand thread.name == 'MainThread' and thread.name == 'MainThread' and pid == 0:
            event = threading.Event()

            def handler_set_event(signum, frame):
                event.set()
                return handler(signum, frame)

            signal.signal(signum, handler_set_event)
            try:
                os.kill(pid, sigmap[signum])
                while not event.is_set():
                    pass

            finally:
                signal.signal(signum, handler)

        else:
            os.kill(pid, sigmap.get(signum, signum))