"""Image-verified visual checkpoint graph anchored by wheel odometry."""
import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from pose_graph import optimize, relative, wrap


class Features:
    def __init__(self, calibration=None):
        self.orb = cv2.ORB_create(nfeatures=2200, fastThreshold=12, edgeThreshold=19)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.calibration = calibration

    def extract(self, image):
        gray = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE) if isinstance(image, (str, Path)) else image
        if gray is None:
            raise ValueError('Cannot read image')
        if gray.ndim == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        if self.calibration:
            width, height = self.calibration['image_size']
            if gray.shape[::-1] != (width, height):
                raise ValueError('Calibration image size differs from camera frame')
            gray = cv2.undistort(gray, np.asarray(self.calibration['matrix']), np.asarray(self.calibration['distortion']))
        equalized = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(gray)
        keys, descriptors = self.orb.detectAndCompute(equalized, None)
        points = np.float32([key.pt for key in keys]).reshape(-1, 2)
        return {'gray': gray, 'points': points, 'descriptors': descriptors}

    def compare(self, reference, query):
        a, b = reference['descriptors'], query['descriptors']
        if a is None or b is None or len(a) < 20 or len(b) < 20:
            return {'matched': False, 'reason': 'insufficient_features', 'inliers': 0}
        forward = self.matcher.knnMatch(a, b, k=2)
        reverse = self.matcher.knnMatch(b, a, k=2)
        reverse_best = {pair[0].queryIdx: pair[0].trainIdx for pair in reverse
                        if len(pair) == 2 and pair[0].distance < .75 * pair[1].distance}
        matches = [pair[0] for pair in forward if len(pair) == 2
                   and pair[0].distance < .75 * pair[1].distance
                   and reverse_best.get(pair[0].trainIdx) == pair[0].queryIdx]
        if len(matches) < 25:
            return {'matched': False, 'reason': 'insufficient_mutual_matches', 'inliers': 0, 'matches': len(matches)}
        source = np.float32([reference['points'][m.queryIdx] for m in matches])
        target = np.float32([query['points'][m.trainIdx] for m in matches])
        homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 3., maxIters=2000, confidence=.995)
        if homography is None or mask is None:
            return {'matched': False, 'reason': 'geometry_failed', 'inliers': 0}
        inliers = mask.ravel().astype(bool)
        count = int(inliers.sum())
        ratio = count / len(matches)
        height, width = reference['gray'].shape
        def coverage(points):
            return abs(cv2.contourArea(cv2.convexHull(points))) / (height * width) if len(points) >= 3 else 0
        area_a, area_b = coverage(source[inliers]), coverage(target[inliers])
        grid = {(min(2, int(x * 3 / width)), min(2, int(y * 3 / height))) for x, y in source[inliers]}
        corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]]).reshape(-1, 1, 2)
        projected = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        sane = bool(np.isfinite(projected).all() and cv2.isContourConvex(projected.astype(np.float32)))
        scale = abs(cv2.contourArea(projected.astype(np.float32))) / (width * height) if sane else 0
        displacement = float(np.median(np.linalg.norm(source[inliers] - target[inliers], axis=1))) / width if count else 1
        matched = bool(count >= 30 and ratio >= .45 and min(area_a, area_b) >= .035
                       and len(grid) >= 4 and sane and .35 <= scale <= 2.8)
        same_view = bool(matched and count >= 50 and .85 <= scale <= 1.18 and displacement <= .07)
        yaw, rotation_residual, same_location = None, None, False
        if matched and self.calibration:
            matrix = np.asarray(self.calibration['matrix'])
            normalized = np.linalg.inv(matrix) @ homography @ matrix
            u, _, vt = np.linalg.svd(normalized)
            rotation = u @ vt
            if np.linalg.det(rotation) > 0:
                yaw = math.degrees(math.atan2(rotation[0, 2], rotation[2, 2]))
                rotation_h = matrix @ rotation @ np.linalg.inv(matrix)
                predicted = cv2.perspectiveTransform(source[inliers].reshape(-1, 1, 2), rotation_h).reshape(-1, 2)
                rotation_residual = float(np.median(np.linalg.norm(predicted - target[inliers], axis=1))) / width
                same_location = bool(count >= 50 and abs(yaw) <= 25 and rotation_residual < .03)
        return {'matched': matched, 'same_view': same_view, 'inliers': count,
                'visual_yaw_degrees': yaw, 'rotation_residual_fraction': rotation_residual,
                'same_location_candidate': same_location,
                'matches': len(matches), 'inlier_ratio': round(ratio, 3),
                'feature_coverage': round(min(area_a, area_b), 3), 'grid_cells': len(grid),
                'image_area_ratio': round(scale, 3), 'median_displacement_fraction': round(displacement, 4),
                'homography': homography.tolist(), 'inlier_points_reference': source[inliers].tolist(),
                'inlier_points_query': target[inliers].tolist()}


def compact(match):
    return {key: value for key, value in match.items()
            if key not in {'inlier_points_reference', 'inlier_points_query', 'homography'}}


def render_match_panel(gray_a, gray_b, match, title, destination):
    panel = np.hstack([cv2.cvtColor(gray_a, cv2.COLOR_GRAY2BGR), cv2.cvtColor(gray_b, cv2.COLOR_GRAY2BGR)])
    width = gray_a.shape[1]
    for a, b in zip(match['inlier_points_reference'][::3], match['inlier_points_query'][::3]):
        cv2.line(panel, tuple(map(int, a)), (int(b[0]) + width, int(b[1])), (60, 220, 100), 1)
    cv2.rectangle(panel, (0, 0), (panel.shape[1], 38), (0, 0, 0), -1)
    cv2.putText(panel, title, (15, 26), cv2.FONT_HERSHEY_SIMPLEX, .65, (230, 240, 230), 1)
    cv2.imwrite(str(destination), panel)


class VisualMemory:
    def __init__(self, folder, calibration=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.features = Features(calibration)
        self.nodes, self.edges, self.revisits, self.cache = [], [], [], []
        self.calibration = calibration

    def add(self, image, pose, label='unknown', timestamp=None):
        feature = self.features.extract(image)
        index = len(self.nodes)
        xyh = [pose['x_mm'] / 1000, pose['y_mm'] / 1000, math.radians(pose['heading_degrees'])]
        node = {'id': index, 'place_id': index, 'photo': str(Path(image).resolve()), 'label': label,
                'pose_odometry': xyh, 'features': len(feature['points']),
                'timestamp': timestamp or time.time()}
        if self.nodes:
            measurement = relative(self.nodes[-1]['pose_odometry'], xyh).tolist()
            distance = math.hypot(measurement[0], measurement[1])
            self.edges.append({'from': index - 1, 'to': index, 'type': 'odometry',
                               'measurement': measurement, 'sigma': [.015 + distance * .05, .015 + distance * .05, math.radians(2)]})
        candidates = []
        for previous in self.nodes:
            if index - previous['id'] < 6:
                continue
            match = self.features.compare(self.cache[previous['id']], feature)
            if match.get('matched'):
                candidates.append((previous, match))
        if candidates:
            previous, match = max(candidates, key=lambda pair: pair[1]['inliers'])
            distance = math.hypot(xyh[0] - previous['pose_odometry'][0], xyh[1] - previous['pose_odometry'][1])
            angle = abs(wrap(xyh[2] - previous['pose_odometry'][2]))
            constraint = bool((match['same_view'] or match.get('same_location_candidate'))
                              and distance < .30 and angle < math.radians(25))
            revisit = {'from': previous['id'], 'to': index, **compact(match),
                       'odometry_separation_m': round(distance, 3), 'pose_constraint_added': constraint}
            self.revisits.append(revisit)
            node['revisit'] = revisit
            if constraint:
                node['place_id'] = previous.get('place_id', previous['id'])
                if label in {'unknown', 'loop waypoint'}:
                    node['label'] = previous['label']
                self.edges.append({'from': previous['id'], 'to': index, 'type': 'visual_revisit',
                                   'measurement': [0., 0., math.radians(match.get('visual_yaw_degrees') or 0.)],
                                   'sigma': [.15, .15, math.radians(5)]})
            render_match_panel(
                self.cache[previous['id']]['gray'], feature['gray'], match,
                f'Reference {previous["id"]} | revisit {index} | {match["inliers"]} geometric inliers',
                self.folder / f'revisit-{previous["id"]}-{index}.jpg')
        self.nodes.append(node)
        self.cache.append(feature)
        annotated = cv2.cvtColor(feature['gray'], cv2.COLOR_GRAY2BGR)
        for x, y in feature['points'][::max(1, len(feature['points']) // 250)]:
            cv2.circle(annotated, (int(x), int(y)), 2, (80, 235, 120), -1)
        cv2.imwrite(str(self.folder / f'features-{index}.jpg'), annotated)
        self.save()
        return node

    def recognize(self, image):
        query = self.features.extract(image)
        candidates = [(node, self.features.compare(self.cache[node['id']], query)) for node in self.nodes]
        candidates = [(node, match) for node, match in candidates if match.get('matched')]
        if not candidates:
            return {'recognized': False, 'reason': 'No geometrically verified visual match'}
        node, match = max(candidates, key=lambda pair: pair[1]['inliers'])
        return {'recognized': True, 'node': node['id'], 'place_id': node.get('place_id', node['id']), 'label': node['label'],
                'reference_photo': node['photo'], 'reference_pose_odometry': node['pose_odometry'],
                'geometry': compact(match), 'warning': 'Appearance match; not a verified metric localization'}

    def save(self):
        poses = [node['pose_odometry'] for node in self.nodes]
        optimized = optimize(poses, self.edges) if any(e['type'] == 'visual_revisit' for e in self.edges) else poses
        data = {'kind': 'experimental_visual_checkpoint_graph', 'nodes': self.nodes, 'edges': self.edges,
                'revisits': self.revisits, 'poses_graph': optimized,
                'calibrated': self.calibration is not None, 'camera_calibration': self.calibration,
                'limits': 'Wheel metric scale; visual image matches and weak revisit constraints. No depth, occupancy, or collision-free routes.'}
        path = self.folder / 'map.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2))
        temporary.replace(path)
        render_map(data, self.folder / 'trajectory.png')
        return data

    @classmethod
    def load(cls, folder):
        data = json.loads((Path(folder) / 'map.json').read_text())
        memory = cls(folder, data.get('camera_calibration'))
        memory.nodes, memory.edges, memory.revisits = data['nodes'], data['edges'], data['revisits']
        memory.cache = [memory.features.extract(node['photo']) for node in memory.nodes]
        return memory


def render_map(data, destination):
    canvas = np.full((720, 1000, 3), (24, 22, 18), np.uint8)
    cv2.putText(canvas, 'R1D1 | visual memory experiment', (35, 45), cv2.FONT_HERSHEY_SIMPLEX, .85, (240, 240, 240), 2)
    cv2.putText(canvas, 'Wheel trajectory + geometrically checked image revisits', (35, 78), cv2.FONT_HERSHEY_SIMPLEX, .55, (180, 185, 190), 1)
    poses = np.array([node['pose_odometry'] for node in data['nodes']])
    if len(poses):
        center = (poses[:, :2].min(axis=0) + poses[:, :2].max(axis=0)) / 2
        span = max(float(np.ptp(poses[:, 0])), float(np.ptp(poses[:, 1])), .8)
        scale = 480 / span
        def pixel(pose): return (int(500 - (pose[1] - center[1]) * scale), int(380 - (pose[0] - center[0]) * scale))
        points = [pixel(p) for p in poses]
        for a, b in zip(points, points[1:]):
            cv2.line(canvas, a, b, (145, 145, 145), 3)
        for revisit in data['revisits']:
            color = (90, 220, 80) if revisit['pose_constraint_added'] else (0, 180, 240)
            cv2.line(canvas, points[revisit['from']], points[revisit['to']], color, 2)
        optimized = data.get('poses_graph', [])
        for a, b in zip(optimized, optimized[1:]):
            cv2.line(canvas, pixel(a), pixel(b), (190, 220, 50), 2)
        groups = []
        for node, point in zip(data['nodes'], points):
            group = next((g for g in groups if math.hypot(g['point'][0] - point[0], g['point'][1] - point[1]) < 14), None)
            if group is None:
                group = {'point': point, 'ids': []}
                groups.append(group)
            group['ids'].append(node['id'])
        for group in groups:
            point, ids = group['point'], group['ids']
            cv2.circle(canvas, point, 6, (70, 220, 230), -1)
            text = str(ids[0]) if len(ids) == 1 else f'{ids[0]}-{ids[-1]}'
            cv2.putText(canvas, text, (point[0] + 8, point[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, .45, (230, 230, 230), 1)
        cv2.circle(canvas, points[0], 10, (80, 230, 90), 2)
        cv2.putText(canvas, 'START', (points[0][0] + 12, points[0][1] + 20), cv2.FONT_HERSHEY_SIMPLEX, .5, (80, 230, 90), 1)
        last, at = poses[-1], points[-1]
        target = (int(at[0] - 25 * math.sin(last[2])), int(at[1] - 25 * math.cos(last[2])))
        cv2.arrowedLine(canvas, at, target, (255, 190, 70), 3)
    lines = [f'Views: {len(data["nodes"])} | image revisits: {len(data["revisits"])} | calibration: {data["calibrated"]}',
             'Positions use wheel odometry; image matching is checked with RANSAC.',
             'Experimental checkpoint graph. Not a floor plan or an obstacle map.']
    for i, text in enumerate(lines):
        cv2.putText(canvas, text, (35, 625 + i * 27), cv2.FONT_HERSHEY_SIMPLEX, .53, (190, 195, 200), 1)
    cv2.imwrite(str(destination), canvas)


def from_log(log_path, folder):
    calibration_file = Path(__file__).resolve().parent / 'runtime/camera-calibration.json'
    calibration = json.loads(calibration_file.read_text()) if calibration_file.exists() else None
    memory = VisualMemory(folder, calibration)
    for line in Path(log_path).read_text().splitlines():
        row = json.loads(line)
        if row.get('kind') == 'roam_step' and row.get('state_sent', {}).get('views', [''])[0] == 'forward_webcam':
            memory.add(row['photo'], row['state_sent']['pose'], row.get('plan', {}).get('room', 'unknown'))
    return memory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--recognize')
    args = parser.parse_args()
    memory = from_log(args.log, args.output)
    result = {'nodes': len(memory.nodes), 'revisits': memory.revisits,
              'map': str(Path(args.output) / 'map.json')}
    if args.recognize:
        result['recognition'] = memory.recognize(args.recognize)
    print(json.dumps(result))
