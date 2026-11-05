"""Collect heading-tagged scan views without a model call between turns."""
import bisect, threading, time, uuid
from inspect_demo import capture
from camera import capture_photo, config
from brain import image_info


def scan(robot, store, root, deadline, degrees=180, continuous=False):
    if type(degrees) is not int or not 1 <= abs(degrees) <= 180: raise ValueError('Invalid scan arc')
    if continuous and config()['primary'] == 'webcam': return moving_scan(robot, store, root, deadline, degrees)
    frames, remaining, direction = [], abs(degrees), (1 if degrees > 0 else -1)
    while True:
        if (root / 'STOP').exists() or deadline - time.monotonic() < 20: raise RuntimeError('Scan stop or deadline')
        state = robot.execute({'action': 'status'})
        if state['reported_velocity_mm_s'] != 0: raise RuntimeError('Scan capture requires stopped robot')
        photo, info = capture(store)
        frames.append({'photo': photo, 'heading_degrees': state['pose']['heading_degrees'],
                       'pose': state['pose'], 'captured_monotonic': time.monotonic(),
                       'brightness': info['brightness'], 'historical_view': True})
        if remaining <= 0: break
        amount = min(30, remaining)
        if (root / 'STOP').exists() or deadline - time.monotonic() < 20: raise RuntimeError('Scan interrupted before turn')
        robot.execute({'action': 'turn', 'degrees': direction * amount}); remaining -= amount
    return frames


def heading_at(timestamp, trajectory):
    times = [point[0] for point in trajectory]
    index = bisect.bisect_right(times, timestamp)
    if index == 0: return trajectory[0][1] % 360
    if index >= len(trajectory): return trajectory[-1][1] % 360
    t0, h0 = trajectory[index - 1]; t1, h1 = trajectory[index]
    return (h0 + (h1 - h0) * (timestamp - t0) / max(1e-9, t1 - t0)) % 360


def moving_scan(robot, store, root, deadline, degrees):
    if (root / 'STOP').exists() or deadline - time.monotonic() < 35: raise RuntimeError('Scan stop or deadline')
    state = robot.execute({'action': 'status'})
    if state['reported_velocity_mm_s'] != 0: raise RuntimeError('Scan must start stopped')
    heading = state['pose']['heading_degrees']; trajectory = [(time.monotonic(), heading)]
    frames, errors, finished = [], [], threading.Event()
    def sample():
        path = store.root / 'photos' / (uuid.uuid4().hex + '-scan.jpg')
        metadata = capture_photo(path, 'webcam')
        frames.append({'photo': str(path), 'captured_monotonic': metadata['captured_monotonic'],
                       'brightness': image_info(path)['brightness'], 'historical_view': True,
                       'heading_source': 'timestamp-interpolated wheel odometry', 'captured_during_scan': True})
    def sampler():
        while not finished.wait(.4):
            if (root / 'STOP').exists(): return
            try: sample()
            except Exception as error: errors.append(error); return
    sample()
    thread = threading.Thread(target=sampler, daemon=True); thread.start()
    remaining, direction = abs(degrees), (1 if degrees > 0 else -1)
    try:
        while remaining:
            if errors: raise RuntimeError('Scan camera failed') from errors[0]
            if (root / 'STOP').exists() or deadline - time.monotonic() < 20: raise RuntimeError('Scan interrupted')
            amount = min(90, remaining)
            motion = robot.execute({'action': 'turn', 'degrees': direction * amount})
            for reading in [motion['sensors_before']] + motion['sensor_samples'] + [motion['sensors_after']]:
                heading += reading['angle_degrees']
                trajectory.append((reading['captured_monotonic'], heading))
            remaining -= amount
    finally:
        finished.set(); thread.join(6)
    if thread.is_alive(): raise RuntimeError('Scan capture did not finish')
    if errors: raise RuntimeError('Scan camera failed') from errors[0]
    final = robot.execute({'action': 'status'})
    if final['reported_velocity_mm_s'] != 0: raise RuntimeError('Scan did not stop')
    sample()
    trajectory.sort(key=lambda point: point[0])
    for frame in frames: frame['heading_degrees'] = heading_at(frame['captured_monotonic'], trajectory)
    frames[-1]['heading_degrees'] = final['pose']['heading_degrees']
    frames[-1]['captured_during_scan'] = False
    count = min(7, len(frames))
    return [frames[round(i * (len(frames) - 1) / max(1, count - 1))] for i in range(count)]
