"""Short status melodies on the original Create's built-in beeper; no motion."""
import argparse, fcntl, json, os, time
from pathlib import Path
from oi import open_port, send, stop, read_exact

MELODIES = {
    'located': [(79, 7), (84, 9)],
    'finished': [(72, 6), (76, 6), (79, 8), (84, 14)],
    'attention': [(64, 12), (60, 18)],
    'test': [(76, 8), (79, 12)],
}


def song_bytes(effect):
    if effect not in MELODIES: raise ValueError('Unknown sound effect')
    notes = MELODIES[effect]
    return [140, 15, len(notes)] + [value for note in notes for value in note]


def play_on_fd(fd, effect):
    data = song_bytes(effect)
    stop(fd); send(fd, data); send(fd, [141, 15]); time.sleep(.06)
    send(fd, [142, 37]); playing = read_exact(fd, 1) == b'\x01'
    time.sleep(sum(duration for _, duration in MELODIES[effect]) / 64 + .05)
    return {'effect': effect, 'robot_reported_playing': playing, 'movement_requested': False}


def play_stopped(root, effect='finished'):
    root = Path(root)
    with (root / 'robot.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = None
        try:
            fd = open_port()
            send(fd, [128]); time.sleep(.15)
            send(fd, [131]); time.sleep(.15)
            stop(fd)
            return play_on_fd(fd, effect)
        finally:
            if fd is not None:
                try: stop(fd)
                finally: os.close(fd)


if __name__ == '__main__':
    from inspect_demo import Store
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--effect', choices=list(MELODIES), default='test')
    args = parser.parse_args(); store = Store(Path(__file__).resolve().parent / 'runtime')
    with store.locked():
        result = play_stopped(store.root, args.effect)
        store.log({'kind': 'sound', **result}); print(json.dumps(result))
