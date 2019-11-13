#!/usr/bin/python3
#coding=utf-8
import socket
import os
import errno
from tornado.ioloop import IOLoop
from tornado.platform.auto import set_close_exec
import redis
import instana
import opentracing as ot
import opentracing.ext.tags as ext
#from instana.tracer import InstanaTracer, InstanaRecorder
from instana.singletons import agent, tracer


os.environ['INSTANA_SERVICE_NAME'] = "udpserver.py"

class UDPServer(object):
    def __init__(self, io_loop=None):
        ot.tracer = tracer
        self.io_loop = io_loop
        self._sockets = {}  # fd -> socket object
        self._pending_sockets = []
        self._started = False
        self.r = redis.Redis()
        self.counter = 0

    def add_sockets(self, sockets):
        if self.io_loop is None:
            self.io_loop = IOLoop.instance()

        for sock in sockets:
            self._sockets[sock.fileno()] = sock
            add_accept_handler(sock, self._on_recive,
                               io_loop=self.io_loop)

    def bind(self, port, address=None, family=socket.AF_UNSPEC, backlog=25):
        sockets = bind_sockets(port, address=address, family=family,
                               backlog=backlog)
        if self._started:
            self.add_sockets(sockets)
        else:
            self._pending_sockets.extend(sockets)

    def start(self, num_processes=1):
        assert not self._started
        self._started = True
        if num_processes != 1:
            process.fork_processes(num_processes)
        sockets = self._pending_sockets
        self._pending_sockets = []
        self.add_sockets(sockets)

    def stop(self):
        for fd, sock in self._sockets.iteritems():
            self.io_loop.remove_handler(fd)
            sock.close()

    def _on_recive(self, data, address):
        parent_span = tracer.active_span
        with ot.tracer.start_active_span('method on_receive', child_of=parent_span) as pscope:
            pscope.span.set_tag(ext.COMPONENT, "Python udp example app")
            pscope.span.set_tag(ext.SPAN_KIND, ext.SPAN_KIND_RPC_SERVER)
            pscope.span.set_tag(ext.PEER_HOSTNAME, "localhost")
            pscope.span.set_tag(ext.PEER_SERVICE, "Peer UDP Server Service")
            pscope.span.set_tag(ext.PEER_PORT, "80")
            # print("before: ", self.r.get(self.counter))
            self.r.set(str(self.counter), data)
            # print("after:", self.r.get(self.counter))
            self.counter = self.counter+1 
            # print(self.r.keys())

def bind_sockets(port, address=None, family=socket.AF_UNSPEC, backlog=25):
    sockets = []
    if address == "":
        address = None
    flags = socket.AI_PASSIVE
    if hasattr(socket, "AI_ADDRCONFIG"):
        flags |= socket.AI_ADDRCONFIG
    for res in set(socket.getaddrinfo(address, port, family, socket.SOCK_DGRAM,
                                  0, flags)):
        af, socktype, proto, canonname, sockaddr = res
        sock = socket.socket(af, socktype, proto)
        set_close_exec(sock.fileno())
        if os.name != 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if af == socket.AF_INET6:
            if hasattr(socket, "IPPROTO_IPV6"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.setblocking(0)
        sock.bind(sockaddr)
        sockets.append(sock)
    return sockets

if hasattr(socket, 'AF_UNIX'):
    def bind_unix_socket(file, mode=0o600, backlog=128):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        set_close_exec(sock.fileno())
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(0)
        try:
            st = os.stat(file)
        except (OSError, err):
            if err.errno != errno.ENOENT:
                raise
        else:
            if stat.S_ISSOCK(st.st_mode):
                os.remove(file)
            else:
                raise ValueError("File %s exists and is not a socket", file)
        sock.bind(file)
        os.chmod(file, mode)
        sock.listen(backlog)
        return sock


def add_accept_handler(sock, callback, io_loop=None):
    if io_loop is None:
        io_loop = IOLoop.instance()

    def accept_handler(fd, events):
        while True:
            try:
                data, address = sock.recvfrom(2500)
            # except (socket.error, e):
            except Exception as e:
                if e.args[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
                    return
                raise
            callback(data, address)
    io_loop.add_handler(sock.fileno(), accept_handler, IOLoop.READ)

if __name__ == '__main__':
    serv = UDPServer()
    serv.bind(80)
    serv.start()
    IOLoop.instance().start()
