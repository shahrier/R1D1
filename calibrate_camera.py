"""Stationary C920 checkerboard calibration; validates diversity and reprojection error."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
from camera import capture_photo
from inspect_demo import Store

DEVICE = '/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_F869A5DF-video-index0'


def diverse(features):
    if len(features) < 15:
        return False
    values = np.array(features)
    return bool(np.ptp(values[:, 0]) >= .12 and np.ptp(values[:, 1]) >= .12
                and (np.ptp(values[:, 2]) >= .06 or np.ptp(values[:, 3]) >= .12))


def detect_board(path):
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    height, width = gray.shape
    found, corners = cv2.findChessboardCornersSB(gray, (9, 6), flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        return gray, (width, height), None, 0.0, None
    points = corners.reshape(-1, 2)
    area = abs(cv2.contourArea(cv2.convexHull(points))) / (width * height)
    centroid = points.mean(axis=0) / [width, height]
    edge = points[8] - points[0]
    feature = np.array([centroid[0], centroid[1], np.sqrt(area), float(np.arctan2(edge[1], edge[0]))])
    return gray, (width, height), corners, area, feature


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'runtime'
    store = Store(root)
    folder = root / 'calibration'
    folder.mkdir(exist_ok=True)
    objects, images, features, paths = [], [], [], []
    world = np.zeros((54, 3), np.float32)
    world[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)
    started = time.monotonic()
    last_status = 0
    with store.locked():
        focus_text = subprocess.check_output(['v4l2-ctl', '-d', DEVICE, '--get-ctrl=focus_absolute'], text=True)
        focus = int(focus_text.strip().split(':')[-1])
        subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=focus_automatic_continuous=0'], check=True)
        subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=focus_absolute=' + str(focus)], check=True)
        if args.resume:
            for saved in sorted(folder.glob('view-*.jpg')):
                _, (width, height), corners, _, feature = detect_board(saved)
                if corners is not None:
                    features.append(feature)
                    images.append(corners); objects.append(world.copy()); paths.append(str(saved))
            print(json.dumps({'resumed_views': len(images), 'diverse': diverse(features)}), flush=True)
        while time.monotonic() - started < args.seconds:
            path = folder / 'current.jpg'
            capture_photo(path, 'webcam')
            gray, (width, height), corners, area, feature = detect_board(path)
            if corners is not None:
                separation = min((np.linalg.norm(feature - f) for f in features), default=1)
                if area >= .025 and separation >= .035:
                    images.append(corners); objects.append(world.copy()); features.append(feature)
                    destination = folder / f'view-{len(images):03d}.jpg'
                    cv2.imwrite(str(destination), gray)
                    paths.append(str(destination))
                    print(json.dumps({'accepted_views': len(images), 'diverse': diverse(features)}), flush=True)
                if len(images) >= 25 and diverse(features) and time.monotonic() - started >= 30:
                    break
            if time.monotonic() - last_status > 10:
                print(json.dumps({'pattern_visible': corners is not None, 'accepted_views': len(images),
                                  'elapsed_s': round(time.monotonic() - started)}), flush=True)
                last_status = time.monotonic()
            time.sleep(.25)
        if not diverse(features):
            raise RuntimeError(f'Insufficient varied checkerboard observations: {len(images)} accepted; calibration not saved')
        rms, matrix, distortion, _, _ = cv2.calibrateCamera(objects, images, (width, height), None, None)
        if not (rms < 1.5 and .4 * width < matrix[0, 0] < 3 * width
                and .4 * width < matrix[1, 1] < 3 * width
                and .2 * width < matrix[0, 2] < .8 * width
                and .2 * height < matrix[1, 2] < .8 * height):
            raise RuntimeError('Calibration failed quality bounds; not saved')
        data = {'camera': 'Logitech C920', 'image_size': [width, height],
                'matrix': matrix.tolist(), 'distortion': distortion.ravel().tolist(),
                'rms_pixels': rms, 'views': len(images), 'focus_absolute': focus,
                'focus_automatic_continuous': False, 'source_images': paths,
                'scale_note': 'Checkerboard grid units; intrinsics only, no measured scene depth'}
        temporary = root / 'camera-calibration.tmp'
        temporary.write_text(json.dumps(data, indent=2))
        os.replace(temporary, root / 'camera-calibration.json')
        print(json.dumps({'calibrated': True, 'rms_pixels': rms, 'views': len(images), 'matrix': matrix.tolist()}), flush=True)


if __name__ == '__main__':
    main()
