#!/usr/bin/env python3
"""PSN (PosiStageNet v2.03) test sender for grandMA3 onPC. Stdlib only.

Sends INFO (1 Hz) and DATA (--rate Hz) packets for one tracker. Positions are
in metres. In onPC 2.5 with the default Map X/Y/Z columns, x is left/right,
y is front/back and z is up/down (MA stage axes, not the spec's y-up).
Setup and findings: docs/PSN.md. Local onPC example:

    python3 tools/psn_test_sender.py --iface 127.0.0.1 --pattern axes

It does not use settings.json and sends nothing to the OSC port.
"""
import argparse, math, socket, struct, sys, time
from contextlib import closing
import ipaddress

FLOAT32_MAX = float.fromhex('0x1.fffffep+127')

def chunk(cid, payload, sub):
    return struct.pack("<I", cid | (len(payload) << 16) | (int(sub) << 31)) + payload

def header(ts_us, frame):
    return chunk(0x0000, struct.pack("<QBBBB", ts_us, 2, 0, frame & 255, 1), False)

def data_packet(trackers, ts_us, frame):
    tl = b"".join(chunk(t, chunk(0x0000, struct.pack("<3f", *p), False), True)
                  for t, p in sorted(trackers.items()))
    return chunk(0x6755, header(ts_us, frame) + chunk(0x0001, tl, True), True)

def info_packet(system, names, ts_us, frame):
    tl = b"".join(chunk(t, chunk(0x0000, n.encode(), False), True)
                  for t, n in sorted(names.items()))
    return chunk(0x6756, header(ts_us, frame) + chunk(0x0001, system.encode(), False)
                 + chunk(0x0002, tl, True), True)

def lerp(a, b, f):
    return a + (b - a) * f

def pattern_pos(name, t, home, r):
    """Return (position, label) for time t seconds."""
    hx, hy, hz = home
    if name == "static":
        return home, "static"
    if name == "circle":
        a = 2 * math.pi * t / 20.0
        return (hx + r * math.cos(a), hy, hz + r * math.sin(a)), "circle"
    # axes: 6 s hold at home, then sweep PSN x, y, z by +-r over 6 s each
    steps = [("hold at home", None), ("PSN x", 0), ("PSN y", 1), ("PSN z", 2)]
    seg = 6.0
    i = int(t // seg) % len(steps)
    label, axis = steps[i]
    f = (t % seg) / seg
    off = r * math.sin(2 * math.pi * f)
    p = list(home)
    if axis is not None:
        p[axis] += off
    return tuple(p), label

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="236.10.10.10")
    ap.add_argument("--port", type=int, default=56565)
    ap.add_argument("--iface", default="127.0.0.1", help="local IP used for multicast egress (127.0.0.1 for onPC on this Mac)")
    ap.add_argument("--tracker", type=int, default=1)
    ap.add_argument("--pattern", choices=["static", "circle", "axes"], default="axes")
    ap.add_argument("--home", type=float, nargs=3, default=[0.0, 0.0, 1.5], metavar=("X", "Y", "Z"))
    ap.add_argument("--radius", type=float, default=2.0)
    ap.add_argument("--rate", type=float, default=30.0)
    ap.add_argument("--seconds", type=float, default=60.0)
    a = ap.parse_args(argv)
    if not math.isfinite(a.rate) or a.rate <= 0 or not math.isfinite(1 / a.rate):
        ap.error('--rate must be finite and positive, with a finite frame interval')
    if not math.isfinite(a.seconds) or not 0 < a.seconds <= (2**64 - 1) // 1_000_000:
        ap.error('--seconds must be finite, positive and fit a PSN timestamp')
    if not 1 <= a.tracker <= 65535:
        ap.error('--tracker must be 1–65535')
    if not 1 <= a.port <= 65535:
        ap.error('--port must be 1–65535')
    if not math.isfinite(a.radius) or not 0 <= a.radius <= FLOAT32_MAX:
        ap.error('--radius must be finite, non-negative and fit a 32-bit float')
    if any(not math.isfinite(v) or abs(v) + a.radius > FLOAT32_MAX for v in a.home):
        ap.error('--home and its radius must fit finite 32-bit PSN coordinates')
    try:
        destination = ipaddress.IPv4Address(a.dest)
        ipaddress.IPv4Address(a.iface)
    except ValueError:
        ap.error('--dest and --iface must be IPv4 addresses')

    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
        s.settimeout(0.2)
        if destination.is_multicast:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(a.iface))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        addr = (a.dest, a.port)
        t0 = time.monotonic(); frame = 0; last_info = -1.0; last_label = None
        print(f"sending to {a.dest}:{a.port} tracker {a.tracker} pattern {a.pattern} for {a.seconds:.0f}s")
        while True:
            t = time.monotonic() - t0
            if t >= a.seconds:
                break
            ts = int(t * 1e6)
            if t - last_info >= 1.0:
                s.sendto(info_packet("Followspot Test", {a.tracker: "Followspot"}, ts, frame), addr)
                last_info = t
            pos, label = pattern_pos(a.pattern, t, a.home, a.radius)
            if label != last_label:
                print(f"t={t:5.1f}s  {label}")
                last_label = label
            s.sendto(data_packet({a.tracker: pos}, ts, frame), addr)
            frame += 1
            now = time.monotonic()
            time.sleep(max(0.0, min(t0 + (frame / a.rate), t0 + a.seconds) - now))
    print("done")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
