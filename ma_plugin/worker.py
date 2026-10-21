"""Owned, bounded file protocol for the embedded grandMA3 helper process."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
if (HERE.parent / 'followspot_core.py').is_file():
    sys.path.insert(0, str(HERE.parent))
from runtime import PluginRuntime, PROTOCOL

# Silence from MA longer than STOP stops output (and ends the helper if no PSN
# stream is held). A held PSN stream survives up to HOLD so a Lua stall does not
# snap the MArker to origin.
LEASE_STOP_SECONDS = 3
LEASE_HOLD_SECONDS = 15


def atomic(path, value):
    def clean(item):
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items() if v is not None}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return item

    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(
        json.dumps(clean(value), ensure_ascii=False, allow_nan=False), encoding='utf-8'
    )
    temporary.replace(path)


def read_json(path):
    try:
        if path.stat().st_size > 1_048_576:
            raise ValueError('Protocol file exceeds 1 MiB.')
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def run(root, token, base, runtime_factory=PluginRuntime, clock=time.monotonic, sleep=time.sleep):
    root, base = Path(root), Path(base)
    runtime, request_id, urgent_id, error = None, 0, 0, ''
    error_fields = []
    reason, ready, lease_lost = '', False, False
    status = {}
    with (base / 'runtime.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            atomic(
                root / 'status.json',
                dict(
                    protocol=PROTOCOL,
                    token=token,
                    ready=False,
                    exit_reason='busy',
                    fault='Another Followspot plugin helper is open. Close it first.',
                ),
            )
            return 73
        try:
            if sys.version_info < (3, 10):
                raise RuntimeError('Python 3.10+ is required.')
            config = read_json(root / 'config.json')
            if config is None:
                raise ValueError('Missing plugin configuration.')
            runtime = runtime_factory(config)
            last_lease, renewed = read(root / 'lease'), clock()
            initial_lease = last_lease
            previous, gated_generation, gate_seq, frame_ack = clock(), 0, 0, 0
            while not reason:
                now = clock()
                lease = read(root / 'lease')
                if lease.startswith(token + ':') and lease != last_lease:
                    last_lease, renewed = lease, now
                    ready = lease != initial_lease
                silent = now - renewed
                if silent > LEASE_STOP_SECONDS:
                    if runtime.stream is None or silent > LEASE_HOLD_SECONDS:
                        if runtime.stream is not None:
                            runtime.fault = (
                                'MA heartbeat lost for 15 s; PSN released and helper stopped. '
                                'Reconnect to continue.'
                            )
                        reason = 'lease_expired'
                        break
                    if not lease_lost:
                        lease_lost = True
                        runtime.hold_after_lease_loss()
                elif lease_lost:
                    lease_lost = False
                urgent = read_json(root / 'urgent.json')
                if urgent and urgent.get('token') == token and urgent.get('id', 0) > urgent_id:
                    urgent_id = urgent['id']
                    request_id = max(request_id, urgent.get('cancel_through', 0))
                    action = urgent.get('action')
                    if action == 'shutdown':
                        reason = 'shutdown'
                        break
                    if action == 'fault':
                        runtime.fail(urgent.get('detail', 'MA output failed.'))
                    elif action == 'stop':
                        runtime.stop()
                    elif action == 'release':
                        runtime.release()
                    gate_seq, gated_generation = 0, runtime.generation
                ack = read_json(root / 'ack.json')
                if ack and ack.get('token') == token:
                    runtime.acknowledge(ack['event_id'])
                    frame_ack = max(frame_ack, ack.get('frame_id', 0))
                request = read_json(root / 'request.json')
                if (
                    ready
                    and request
                    and request.get('token') == token
                    and request.get('id', 0) > request_id
                ):
                    request_id, error, error_fields = request['id'], '', []
                    try:
                        runtime.command(request['action'], request.get('payload'))
                    except Exception as exc:
                        error = str(exc)
                        # SettingsError names the fields the panel should highlight.
                        error_fields = [str(field) for field in getattr(exc, 'fields', ())]
                        runtime.message = error
                if runtime.generation != gated_generation:
                    gated_generation = runtime.generation
                    gate_seq = runtime.frame['seq'] if runtime.frame else 0
                if lease_lost:
                    runtime.check_stream()
                elif ready and frame_ack >= gate_seq:
                    runtime.tick(max(0, now - previous))
                previous = now
                status = runtime.snapshot()
                status.update(
                    token=token,
                    ready=ready,
                    request_id=request_id,
                    request_error=error,
                    request_error_fields=error_fields,
                    pid=os.getpid(),
                    python=sys.version.split()[0],
                    heartbeat=clock(),
                    urgent_id=urgent_id,
                    lease_lost=lease_lost,
                )
                atomic(root / 'status.json', status)
                sleep(max(0, 1 / 30 - (clock() - now)))
        except Exception as exc:
            error, reason = str(exc), 'error'
        finally:
            if runtime:
                try:
                    runtime.close()
                except Exception as exc:
                    error = (error + '; cleanup: ' + str(exc)).strip('; ')
                status = runtime.snapshot()
            status.update(
                protocol=PROTOCOL,
                token=token,
                ready=False,
                exit_reason=reason,
                request_id=request_id,
                request_error=error,
            )
            atomic(root / 'status.json', status)
    return 1 if reason == 'error' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('token')
    parser.add_argument('--base', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.root, args.token, args.base))
