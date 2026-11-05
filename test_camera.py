import io,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
import camera


class CameraTests(unittest.TestCase):
    def test_stale_camera_and_missing_freshness_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            response = Mock(); response.headers = {}
            with patch.object(camera.requests, 'get', return_value=response):
                with self.assertRaises(RuntimeError): camera.capture_photo(Path(folder) / 'image.jpg', 'webcam')
                response.headers = {'X-Frame-Age-Seconds': '30', 'X-Frame-Monotonic': str(time.monotonic() - 30)}
                with self.assertRaises(RuntimeError): camera.capture_photo(Path(folder) / 'image.jpg', 'webcam')


    def test_fresh_webcam_image_is_validated_and_saved(self):
        image = Image.new('RGB', (640, 480), 'white'); data = io.BytesIO(); image.save(data, 'JPEG')
        response = Mock(); response.content = data.getvalue()
        response.headers = {'X-Frame-Age-Seconds': '0.1', 'X-Frame-Monotonic': str(time.monotonic())}
        with tempfile.TemporaryDirectory() as folder, patch.object(camera.requests, 'get', return_value=response):
            path = Path(folder) / 'image.jpg'; camera.capture_photo(path, 'webcam')
            with Image.open(path) as saved: self.assertEqual(saved.size, (640, 480))
