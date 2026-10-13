"""Capture protocols and timing. No Blender API calls, including on the receiver thread."""
from collections import deque
from dataclasses import dataclass
import math
import socket
import struct
import threading
import time

# Epic/Apple wire order (not Face Cap's differently ordered expression list).
ARKIT_NAMES = tuple("""eyeBlinkLeft eyeLookDownLeft eyeLookInLeft eyeLookOutLeft eyeLookUpLeft
eyeSquintLeft eyeWideLeft eyeBlinkRight eyeLookDownRight eyeLookInRight eyeLookOutRight
eyeLookUpRight eyeSquintRight eyeWideRight jawForward jawLeft jawRight jawOpen mouthClose
mouthFunnel mouthPucker mouthLeft mouthRight mouthSmileLeft mouthSmileRight mouthFrownLeft
mouthFrownRight mouthDimpleLeft mouthDimpleRight mouthStretchLeft mouthStretchRight
mouthRollLower mouthRollUpper mouthShrugLower mouthShrugUpper mouthPressLeft mouthPressRight
mouthLowerDownLeft mouthLowerDownRight mouthUpperUpLeft mouthUpperUpRight browDownLeft
browDownRight browInnerUp browOuterUpLeft browOuterUpRight cheekPuff cheekSquintLeft
cheekSquintRight noseSneerLeft noseSneerRight tongueOut""".split())


@dataclass
class Sample:
    time: float
    values: dict
    subject: str = ""


def decode_live_link(data):
    """Read the ARKit Live Link Face packet, rejecting truncated/nonfinite payloads."""
    if len(data) < 62:
        raise ValueError("Truncated Live Link Face header")
    length = struct.unpack_from("!i", data, 41)[0]
    if not 0 <= length <= 1024:
        raise ValueError("Invalid subject length")
    end = 45 + length
    if len(data) < end + 17:
        raise ValueError("Truncated Live Link Face subject")
    subject = data[45:end].decode("utf-8").rstrip("\0")
    count = data[end + 16]
    if count != 61 or len(data) != end + 17 + count * 4:
        raise ValueError("Expected 61 ARKit values; use Live Link Face ARKit mode")
    values = struct.unpack_from("!61f", data, end + 17)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Nonfinite capture value")
    return subject, {name: max(0.0, min(1.0, value)) for name, value in zip(ARKIT_NAMES, values)}


def decode_ifacial(data):
    values = {}
    for field in data.decode("utf-8").split("|"):
        name, sep, value = field.partition("-")
        name = name.replace("_L", "Left").replace("_R", "Right")
        if sep and name in ARKIT_NAMES:
            number = float(value) / 100
            if not math.isfinite(number):
                raise ValueError("Nonfinite capture value")
            values[name] = max(0.0, min(1.0, number))
    if not values:
        raise ValueError("No iFacialMocap expressions")
    return "iFacialMocap", values


class Receiver:
    def __init__(self, host, port, protocol="EPIC", subject=""):
        self.queue = deque(maxlen=18000)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.bad_packets = 0
        self.dropped = 0
        self.error = ""
        self.subject = subject
        self.protocol = protocol
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((host, port))  # Fail synchronously; never claim a failed bind succeeded.
            self.sock.settimeout(.1)
        except Exception:
            self.sock.close()
            raise
        self.thread = threading.Thread(target=self._run, daemon=True, name="MetaMorphosis Capture")
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as error:
                if not self.stop_event.is_set():
                    self.error = str(error)
                break
            try:
                subject, values = (decode_live_link(data) if self.protocol == "EPIC" else decode_ifacial(data))
                if self.subject and subject != self.subject:
                    continue
                self.subject = subject  # Lock onto one actor until disconnected.
                sample = Sample(time.monotonic(), values, subject)
                with self.lock:
                    if len(self.queue) == self.queue.maxlen:
                        self.dropped += 1
                    self.queue.append(sample)
            except (ValueError, UnicodeError, struct.error):
                self.bad_packets += 1

    def drain(self):
        with self.lock:
            result = list(self.queue)
            self.queue.clear()
        return result

    def close(self):
        self.stop_event.set()
        self.sock.close()
        self.thread.join(timeout=.5)


class Recording:
    """Wall-clock recording independent of viewport speed; never wraps the timeline."""
    def __init__(self, now, frame_start, frame_end, fps, extend):
        self.start_time = now + 3.0
        self.frame_start, self.frame_end = frame_start, frame_end
        self.fps, self.extend = fps, extend
        self.samples = []

    def frame(self, now):
        return self.frame_start + max(0, int((now - self.start_time) * self.fps + 1e-6))

    def finished(self, now):
        return not self.extend and self.frame(now) > self.frame_end

    def add(self, sample):
        if sample.time >= self.start_time and not self.finished(sample.time):
            self.samples.append(sample)


def resample(samples, fps, start_time=None):
    """Yield frame offsets and interpolated coefficients at the scene rate, including gaps."""
    if not samples:
        return
    start = samples[0].time if start_time is None else start_time
    # Missing opening frames stay unkeyed instead of inventing a performance.
    first = max(0, math.ceil((samples[0].time - start) * fps - 1e-6))
    last = max(first, math.floor((samples[-1].time - start) * fps + 1e-6))
    index = 0
    for frame in range(first, last + 1):
        t = start + frame / fps
        while index + 1 < len(samples) and samples[index + 1].time <= t:
            index += 1
        a = samples[index]
        b = samples[min(index + 1, len(samples) - 1)]
        alpha = max(0.0, min(1.0, (t - a.time) / (b.time - a.time))) if b.time > a.time else 0.0
        yield frame, {n: a.values.get(n, 0.0) * (1-alpha) + b.values.get(n, 0.0) * alpha for n in ARKIT_NAMES}
