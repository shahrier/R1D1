"""C920 MJPEG service with fresh snapshots, stale-frame rejection and concurrent clients."""
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEVICE = '/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_F869A5DF-video-index0'
condition = threading.Condition()
latest_frame = None
latest_time = 0.0
shutdown = threading.Event()
process = None


def capture_loop():
    global latest_frame, latest_time, process
    while not shutdown.is_set():
        try:
            process = subprocess.Popen(['ffmpeg', '-nostdin', '-loglevel', 'error',
                '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', '640x480',
                '-framerate', '15', '-i', DEVICE, '-c', 'copy', '-f', 'mjpeg', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            buffer = b''
            while not shutdown.is_set():
                chunk = process.stdout.read1(65536)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    start = buffer.find(b'\xff\xd8')
                    end = buffer.find(b'\xff\xd9', start + 2 if start >= 0 else 0)
                    if start < 0 or end < 0:
                        break
                    frame, buffer = buffer[start:end + 2], buffer[end + 2:]
                    with condition:
                        latest_frame, latest_time = frame, time.monotonic()
                        condition.notify_all()
                if len(buffer) > 4_000_000:
                    buffer = b''
        finally:
            with condition:
                latest_frame, latest_time = None, 0.0
                condition.notify_all()
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                if process.stdout:
                    process.stdout.close()
            shutdown.wait(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        target = urlparse(self.path)
        if target.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h2>R1D1 camera</h2><img src="/stream" style="max-width:100%">')
            return
        if target.path == '/snap':
            try:
                after = float(parse_qs(target.query).get('after', ['0'])[0])
                if not 0 <= after <= time.monotonic() + 1:
                    raise ValueError
            except ValueError:
                return self.send_error(400, 'Invalid frame timestamp')
            deadline = time.monotonic() + 3
            with condition:
                while not (latest_frame and latest_time >= after and time.monotonic() - latest_time <= 1.5):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return self.send_error(503, 'No fresh frame')
                    condition.wait(remaining)
                frame, timestamp = latest_frame, latest_time
            self.send_response(200)
            for k, v in (('Content-Type', 'image/jpeg'), ('Content-Length', str(len(frame))),
                         ('Cache-Control', 'no-store'), ('X-Frame-Monotonic', str(timestamp)),
                         ('X-Frame-Age-Seconds', str(time.monotonic() - timestamp))):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(frame)
            return
        if target.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=r1d1frame')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                while not shutdown.is_set():
                    with condition:
                        frame = latest_frame if time.monotonic() - latest_time <= 1.5 else None
                    if frame:
                        self.wfile.write(b'--r1d1frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                            + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
                    shutdown.wait(.067)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            return
        self.send_error(404)

    def log_message(self, *args):
        pass


def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
    thread = threading.Thread(target=capture_loop, daemon=True)
    thread.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        if process is not None:
            process.terminate()
        server.server_close()
        thread.join(3)


if __name__ == '__main__':
    main()
