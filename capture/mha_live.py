"""Direct Live Link Face MHA transport. Network threads never access Blender."""
from collections import deque
import json
import math
import socket
import struct
import threading
import time

from .mocap_core import Sample

HEADER = b'CPSCONTROL\0'


def decode_frame(data, names, subject_id):
    if len(data) < 4:
        raise ValueError('Truncated MHA frame')
    version, length = struct.unpack_from('<HH', data)
    if version != 1 or length > 1024 or len(data) < 4 + length + 18:
        raise ValueError('Unsupported MHA frame header')
    subject = data[4:4+length].decode('utf-8')
    offset = 4 + length
    frame, subframe, numerator, denominator, count = struct.unpack_from('<ifiiH', data, offset)
    offset += 18
    if (subject != subject_id or count != len(names) or numerator <= 0 or denominator <= 0
            or not math.isfinite(subframe) or not 0 <= subframe < 1
            or len(data) != offset + 2*count + 24):
        raise ValueError('Invalid MHA frame schema or timing')
    values = struct.unpack_from(f'<{count}H', data, offset)
    head = struct.unpack_from('<6f', data, offset + count*2)
    if not all(math.isfinite(value) for value in head):
        raise ValueError('Invalid MHA head pose')
    return (frame + subframe)*denominator/numerator, dict(zip(names, (v/65535 for v in values)))


class ControlSession:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=3)
        self.session = 'handshake'
        self.serial = 0

    def _read(self, size):
        parts = bytearray()
        while len(parts) < size:
            block = self.sock.recv(size-len(parts))
            if not block:
                raise ConnectionError('iPhone disconnected')
            parts.extend(block)
        return bytes(parts)

    def request(self, path, body=None):
        self.serial += 1
        message = dict(sessionId=self.session, addressPath=path, transactionId=self.serial,
                       timestamp=int(time.time()*1000), type='request')
        if body is not None:
            message['body'] = body
        payload = json.dumps(message).encode('utf-8')
        self.sock.sendall(HEADER + struct.pack('<HI', 1, len(payload)) + payload)
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if self._read(len(HEADER)) != HEADER:
                raise ValueError('Invalid phone session header')
            version, size = struct.unpack('<HI', self._read(6))
            if version != 1 or size > 1024*1024:
                raise ValueError('Unsupported phone protocol')
            reply = json.loads(self._read(size).decode('utf-8'))
            if reply.get('type') != 'response' or reply.get('transactionId') != self.serial:
                continue
            if reply.get('addressPath') != path:
                raise ValueError('Unexpected phone response')
            if reply.get('error'):
                raise RuntimeError(str(reply['error']))
            return reply.get('body', {})
        raise TimeoutError('Phone did not answer the request')

    def close(self):
        self.sock.close()


class MHAReceiver:
    def __init__(self, host, port, phone, control_port=14785, subject=''):
        if not phone.strip():
            raise ValueError('Enter the iPhone Wi-Fi address')
        self.queue = deque(maxlen=18000)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.bad_packets = self.dropped = 0
        self.error = ''
        self.subject = subject
        self.phone = phone.strip()
        self.control_port = control_port
        self.names = ()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((host, port))
            self.sock.settimeout(.1)
        except Exception:
            self.sock.close()
            raise
        self.thread = threading.Thread(target=self._run, daemon=True, name='MetaMorphosis MHA')
        self.thread.start()

    def _run(self):
        control = None
        try:
            control = ControlSession(self.phone, self.control_port)
            control.session = control.request('/session/start')['sessionId']
            subjects = control.request('/stream/subjects')['subjects']
            candidates = [s for s in subjects if s.get('animationMetadata', {}).get('type') == 'mha'
                          and (not self.subject or self.subject in (s['name'], s['id']))]
            if len(candidates) != 1:
                raise ValueError('Enable MetaHuman Animator and Realtime Animation on the phone; select one subject')
            selected = candidates[0]
            metadata = selected['animationMetadata']
            if metadata.get('version') != 1:
                raise ValueError('Unsupported MetaHuman Animator control version')
            self.names = tuple(metadata['controls'])
            if not self.names or len(self.names) > 4096 or len(set(self.names)) != len(self.names):
                raise ValueError('Invalid phone control list')
            self.subject = selected['name']
            control.request('/stream/start', dict(streamPort=self.sock.getsockname()[1],
                            subjects=[dict(id=selected['id'], name=self.subject)]))
            keepalive = time.monotonic()
            first_time = last_time = None
            anchor = None
            peer_ip = control.sock.getpeername()[0]
            while not self.stop_event.is_set():
                if time.monotonic()-keepalive >= 4:
                    control.request('/session/keep-alive')
                    keepalive = time.monotonic()
                try:
                    data, peer = self.sock.recvfrom(65535)
                except socket.timeout:
                    continue
                if peer[0] != peer_ip:
                    continue
                try:
                    stamp, values = decode_frame(data, self.names, selected['id'])
                    if last_time is not None and stamp <= last_time:
                        # Drop duplicates and out-of-order UDP frames.
                        continue
                    if first_time is None:
                        first_time, anchor = stamp, time.monotonic()
                    last_time = stamp
                    sample = Sample(anchor + stamp-first_time, values, self.subject)
                    with self.lock:
                        if len(self.queue) == self.queue.maxlen:
                            self.dropped += 1
                        self.queue.append(sample)
                except (ValueError, UnicodeError, struct.error):
                    self.bad_packets += 1
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error = str(exc)
        finally:
            if control:
                try:
                    if control.session != 'handshake':
                        control.request('/stream/stop')
                        control.request('/session/stop')
                except Exception:
                    pass
                control.close()
            self.sock.close()

    def drain(self):
        with self.lock:
            samples = list(self.queue)
            self.queue.clear()
        return samples

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=.2)
