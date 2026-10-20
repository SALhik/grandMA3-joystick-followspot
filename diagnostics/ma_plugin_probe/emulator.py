"""Synthetic input only: no HID access, network, lighting output or app imports."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time


def sample_at(elapsed):
    """X/Y/zoom are normalized axes; slider is percent; buttons are a bit mask."""
    phase = int(elapsed) % 4
    return ((0.0, 0.0, 25.0, 0.0, 0),
            (0.75, -0.5, 60.0, 0.5, 1),
            (0.0, 0.0, 60.0, 0.0, 0),
            (-0.75, 0.5, 80.0, -0.5, 2))[phase]


def atomic(root, name, text):
    temporary = root / (name + '.' + str(os.getpid()) + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(root / name)


def read(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def run(root, token, mode, duration=4.1, lease_timeout=1.2):
    root = Path(root)
    with (root / 'reader.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 73  # Never overwrite the active reader's ready/result files.
        started = time.monotonic()
        last_lease_time, last_lease = started, None
        samples, reason, detail, code = 0, 'unknown', '', 0
        try:
            if sys.version_info < (3, 10):
                raise RuntimeError('Python 3.10 or newer is required')
            atomic(root, 'ready', 'FS_DIAGNOSTIC_1\t%s\t%s\t%d' % (
                token, sys.version.split()[0], os.getpid()))
            deadline = started
            while True:
                now = time.monotonic()
                if read(root / 'stop') == token:
                    reason = 'requested_stop'
                    break
                lease = read(root / 'lease')
                if lease.startswith(token + ':') and lease != last_lease:
                    last_lease, last_lease_time = lease, now
                if now - last_lease_time > lease_timeout:
                    reason = 'lease_expired'
                    break
                elapsed = now - started
                if mode == 'fault' and elapsed >= 0.75:
                    reason, detail, code = 'injected_fault', 'Intentional diagnostic failure', 2
                    break
                if elapsed >= duration:
                    reason = 'completed'
                    break
                samples += 1
                x, y, slider, zoom, buttons = sample_at(elapsed)
                atomic(root, 'sample', '%s\t%d\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%d' % (
                    token, samples, elapsed, x, y, slider, zoom, buttons))
                deadline += 1 / 30
                time.sleep(max(0, deadline - time.monotonic()))
        except Exception as exc:
            reason, detail, code = 'reader_error', str(exc), 1
        finally:
            result = dict(protocol='FS_DIAGNOSTIC_1', token=token, mode=mode,
                          reason=reason, detail=detail, samples=samples,
                          elapsed=time.monotonic() - started, pid=os.getpid(),
                          python=sys.version.split()[0], lighting_output=False)
            atomic(root, 'result.json', json.dumps(result, indent=2))
            atomic(root, 'helper-report.txt', '\n'.join('%s=%s' % item for item in result.items()))
            atomic(root, 'exit', token + '\t' + reason)
        return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('token')
    parser.add_argument('mode', choices=('normal', 'watchdog', 'fault'))
    parser.add_argument('--duration', type=float, default=4.1)
    parser.add_argument('--lease-timeout', type=float, default=1.2)
    args = parser.parse_args()
    if not 0 < args.duration <= 8 or not 0.05 <= args.lease_timeout <= 3:
        parser.error('Diagnostic duration must be 0–8 seconds and lease timeout 0.05–3 seconds')
    return run(args.root, args.token, args.mode, args.duration, args.lease_timeout)


if __name__ == '__main__':
    raise SystemExit(main())
