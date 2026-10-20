"""Finite joystick-free OSC MArker test, using the application's output controller."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time

from followspot_core import Controller, OscSender, Settings


def atomic(root, name, text):
    temporary = root / (name + '.' + str(os.getpid()) + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(root / name)


def read(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def load_settings(path):
    settings = Settings.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))
    if settings.control_mode != 'marker' or settings.position_output != 'osc':
        raise ValueError('This movement diagnostic requires MArker mode with OSC output; settings were not changed.')
    if settings.test_period > 30:
        raise ValueError('This finite diagnostic requires a test period of 2–30 seconds.')
    # This stage exercises only the target and its saved test-brightness executor.
    settings.zoom_enabled, settings.buttons = False, {}
    return settings


def run(root, token, sender_factory=OscSender, clock=time.monotonic,
        sleep=time.sleep, lease_timeout=1.2):
    root = Path(root)
    with (root / 'reader.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 73
        started = clock()
        initial_lease = read(root / 'lease')
        last_lease_time, last_lease = started, initial_lease
        reason, detail, code, sent, samples = 'unknown', '', 0, 0, 0
        sender, controller, settings = None, None, None

        def stopped(now):
            nonlocal last_lease, last_lease_time
            if read(root / 'stop') == token:
                return 'requested_stop'
            lease = read(root / 'lease')
            if lease.startswith(token + ':') and lease != last_lease:
                last_lease, last_lease_time = lease, now
            if not lease.startswith(token + ':') or now - last_lease_time > lease_timeout:
                return 'lease_expired'
            return None

        try:
            if sys.version_info < (3, 10):
                raise RuntimeError('Python 3.10 or newer is required')
            settings = load_settings(root / 'settings.json')
            reason = stopped(clock())
            if not reason:
                sender = sender_factory(settings.host, settings.port, settings.prefix)
                with (root / 'sent.jsonl').open('w', encoding='utf-8') as log:
                    def send(address, value):
                        nonlocal sent
                        sender.send(address, value)
                        sent += 1
                        log.write(json.dumps(dict(elapsed=clock() - started,
                            address=('/' + settings.prefix if settings.prefix else '') + address,
                            value=value)) + '\n')
                        log.flush()

                    controller = Controller(settings, send)
                    # Observe a new heartbeat after all potentially slow setup.
                    # Neither a pre-launch file nor a lease from DNS lookup proves
                    # that Lua is still running and authorizing the first output.
                    initial_lease = read(root / 'lease')
                    last_lease_time, last_lease = clock(), initial_lease
                    reason = stopped(clock())
                    while not reason and last_lease == initial_lease:
                        sleep(1 / 30)
                        reason = stopped(clock())
                    if not reason:
                        controller.start(test=True)
                        atomic(root, 'ready', 'FS_MOVEMENT_1\t%s\t%s\t%d' % (
                            token, sys.version.split()[0], os.getpid()))
                        previous = clock()
                        deadline = previous
                        while True:
                            now = clock()
                            reason = stopped(now)
                            if reason:
                                break
                            remaining = settings.test_period - controller.test_time
                            if remaining <= 1e-8:
                                reason = 'completed'
                                break
                            if now - started > settings.test_period + 2:
                                reason = 'timing_gap'
                                break
                            controller.tick(None, min(now - previous, remaining))
                            previous = now
                            samples += 1
                            xyz = controller.motion.xyz
                            atomic(root, 'sample', '%s\t%d\t%.6f\t%.6f\t%.6f\t%.6f\t%d' % (
                                token, samples, controller.test_time, *xyz, sent))
                            deadline += 1 / 30
                            sleep(max(0, deadline - clock()))
        except Exception as exc:
            reason, detail, code = 'output_error', str(exc), 1
        finally:
            if controller:
                controller.stop()
            if sender:
                sender.close()
            result = dict(protocol='FS_MOVEMENT_1', token=token, reason=reason,
                          detail=detail, messages_sent=sent, samples=samples,
                          elapsed=clock() - started, pid=os.getpid(),
                          python=sys.version.split()[0], lighting_output=True,
                          reception_verified=False,
                          last_xyz=[round(v, 6) for v in controller.motion.xyz] if controller else None)
            atomic(root, 'result.json', json.dumps(result, indent=2))
            atomic(root, 'helper-report.txt', '\n'.join('%s=%s' % item for item in result.items()))
            atomic(root, 'exit', token + '\t' + reason)
        return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('token')
    args = parser.parse_args()
    raise SystemExit(run(args.root, args.token))
