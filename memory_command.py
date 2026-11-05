"""Read-only visual-memory commands for the paired Muse app."""
import json
import uuid
from pathlib import Path

from inspect_demo import Store, capture, send_report
from visual_memory import VisualMemory, render_match_panel


def active_folder(root):
    pointer = json.loads((root / 'visual-map-active.json').read_text())
    folder = Path(pointer['folder']).resolve()
    if not folder.is_relative_to((root / 'maps').resolve()):
        raise ValueError('Map pointer is outside project maps')
    return folder


def run(mode='recognize', send=True):
    if mode not in {'recognize', 'map'}:
        raise ValueError('Mode must be recognize or map')
    root = Path(__file__).resolve().parent / 'runtime'
    store = Store(root)
    with store.locked():
        folder = active_folder(root)
        if mode == 'map':
            data = json.loads((folder / 'map.json').read_text())
            result = {'views': len(data['nodes']), 'revisits': len(data['revisits']),
                      'calibrated': data['calibrated'], 'limits': data['limits']}
            if send:
                result['delivery'] = send_report(
                    f"R1D1 visual memory: {result['views']} recorded views, {result['revisits']} image revisit candidates. "
                    "Positions use wheel odometry. This is an experimental checkpoint graph, not a floor plan or obstacle map.",
                    str(folder / 'trajectory.png'))
            return result
        memory = VisualMemory.load(folder)
        photo, _ = capture(store)
        result = memory.recognize(photo)
        report_photo = photo
        if result['recognized']:
            index = result['node']
            query = memory.features.extract(photo)
            match = memory.features.compare(memory.cache[index], query)
            report_photo = str(folder / ('recognition-' + uuid.uuid4().hex[:8] + '.jpg'))
            render_match_panel(
                memory.cache[index]['gray'], query['gray'], match,
                f'Remembered view | current view | {match["inliers"]} geometric inliers',
                report_photo)
        if send:
            text = (f"R1D1 found a geometrically verified image match to recorded view {result['node'] + 1} "
                    f"({result['label']}); {result['geometry']['inliers']} inlier features. "
                    "This is appearance-based place recognition, not a verified metric position or safe route."
                    if result['recognized'] else
                    'R1D1 could not verify a match to its saved views. No location or safe-route claim.')
            result['delivery'] = send_report(text, report_photo)
        store.log({'kind': 'memory_recognition', 'photo': photo, **result})
        return result
