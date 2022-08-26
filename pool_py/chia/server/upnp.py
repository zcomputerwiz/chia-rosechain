# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\upnp.py
import logging, threading
from queue import Queue
from typing import Optional
try:
    import miniupnpc
except ImportError:
    pass

log = logging.getLogger(__name__)

class UPnP:
    thread = None
    thread: Optional[threading.Thread]
    queue = Queue()
    queue: Queue

    def __init__(self):

        def run():
            try:
                self.upnp = miniupnpc.UPnP()
                self.upnp.discoverdelay = 30
                self.upnp.discover()
                self.upnp.selectigd()
                keep_going = True
                while keep_going:
                    msg = self.queue.get()
                    if msg[0] == 'remap':
                        port = msg[1]
                        log.info(f"Attempting to enable UPnP (open up port {port})")
                        try:
                            self.upnp.deleteportmapping(port, 'TCP')
                        except Exception as e:
                            try:
                                log.info(f"Removal of previous portmapping failed. This does not indicate an error: {e}")
                            finally:
                                e = None
                                del e

                        self.upnp.addportmapping(port, 'TCP', self.upnp.lanaddr, port, 'chiarose', '')
                        log.info(f"Port {port} opened with UPnP. lanaddr {self.upnp.lanaddr} external: {self.upnp.externalipaddress()}")
                    else:
                        if msg[0] == 'release':
                            port = msg[1]
                            log.info(f"UPnP, releasing port {port}")
                            self.upnp.deleteportmapping(port, 'TCP')
                            log.info(f"UPnP, Port {port} closed")
                        else:
                            if msg[0] == 'shutdown':
                                keep_going = False

            except Exception as e:
                try:
                    log.info('UPnP failed. This is not required to run chia, it allows incoming connections from other peers.')
                    log.info(e)
                finally:
                    e = None
                    del e

        self.thread = threading.Thread(target=run)
        self.thread.start()

    def remap(self, port):
        self.queue.put(('remap', port))

    def release(self, port):
        self.queue.put(('release', port))

    def shutdown(self):
        if not self.thread:
            return
        self.queue.put(('shutdown', ))
        log.info('UPnP, shutting down thread')
        self.thread.join()
        self.thread = None

    def __del__(self):
        self.shutdown()