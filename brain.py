"""Meta Responses client with mission conversation and encrypted reasoning replay."""
import base64, json, os, tempfile, time
from pathlib import Path
import requests
from PIL import Image, ImageStat

ENDPOINT = 'https://api.meta.ai/v1/responses'
MODEL = 'muse-wonder-1.0'
MODEL_RATES = {
    'muse-wonder-1.0': (4., .20, 20.),
    'muse-spark-1.3': (1.25, .15, 4.25),
    'muse-spark-1.3-contributor': (.10, .002, .20),
}


def image_info(path):
    with Image.open(path) as image:
        return {'width': image.width, 'height': image.height,
                'brightness': round(ImageStat.Stat(image.convert('L')).mean[0], 1)}


def prepare_image(source, destination):
    with Image.open(source) as image:
        image = image.convert('RGB'); image.thumbnail((1280, 720)); image.save(destination, 'JPEG', quality=80)
    return image_info(destination)


class Brain:
    def __init__(self, max_calls=25, deadline=None, retain_context=True, session_path=None,
                 reasoning_effort='medium', max_output_tokens=2048, model=MODEL):
        if model not in MODEL_RATES: raise ValueError('Unsupported configured model')
        self.model = model
        self.key = os.environ.get('META_MODEL_API_KEY', '').strip() or (
            Path.home() / '.config/r1d1/meta_api_key').read_text().strip()
        if not self.key: raise RuntimeError('Meta API key is empty')
        if reasoning_effort not in {'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ValueError('Invalid reasoning effort')
        self.calls, self.max_calls, self.deadline = 0, max_calls, deadline or time.monotonic() + 600
        self.estimated_usd, self.last, self.output = 0., None, []
        self.retain_context, self.reasoning_effort, self.max_output_tokens = retain_context, reasoning_effort, max_output_tokens
        self.session_path = Path(session_path) if session_path else None
        self.history, self.turns = [], 0
        if self.session_path and self.session_path.exists():
            saved = json.loads(self.session_path.read_text())
            if saved.get('version') != 1 or saved.get('model') != self.model or not isinstance(saved.get('items'), list):
                raise ValueError('Invalid saved conversation; refusing to reset silently')
            self.history, self.turns = saved['items'], saved.get('turns', 0)

    def _save_session(self):
        if not self.session_path: return
        self.session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='conversation-', suffix='.tmp', dir=self.session_path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'version': 1, 'model': self.model, 'turns': self.turns, 'items': self.history}, stream)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.session_path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def _message(self, state, images):
        content = [{'type': 'input_text', 'text': json.dumps(state)}]
        for path in images:
            info = image_info(path)
            if info['width'] > 1280 or info['height'] > 720: raise ValueError('Image exceeds upload bounds')
            encoded = base64.b64encode(Path(path).read_bytes()).decode('ascii')
            content.append({'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + encoded})
        return {'role': 'user', 'content': content}

    def _request(self, instruction, new_items, tokens=None, tools=None, carry=True, effort=None):
        remaining = self.deadline - time.monotonic()
        if self.calls >= self.max_calls or remaining <= 0:
            raise RuntimeError('Model call or mission time budget exhausted')
        carry = bool(carry and self.retain_context)
        context = self.history + new_items if carry else new_items
        if len(context) > 1500:
            raise RuntimeError('Conversation item budget reached; stopped instead of forgetting history')
        payload = {'model': self.model, 'instructions': instruction,
                   'reasoning': {'effort': effort or self.reasoning_effort},
                   'max_output_tokens': tokens if tokens is not None else self.max_output_tokens,
                   'store': False, 'input': context}
        if carry: payload['include'] = ['reasoning.encrypted_content']
        if tools is not None: payload['tools'], payload['parallel_tool_calls'] = tools, False
        self.calls += 1; started = time.monotonic()
        try:
            response = requests.post(ENDPOINT, headers={'Authorization': 'Bearer ' + self.key}, json=payload,
                                     timeout=(min(5, remaining), min(60, remaining)))
        except requests.RequestException as error:
            raise RuntimeError('Meta API network failure: ' + type(error).__name__) from None
        if not response.ok:
            raise RuntimeError('Meta API HTTP ' + str(response.status_code) + '; no automatic retry or history reset')
        data = response.json(); usage = data.get('usage', {})
        cached = usage.get('input_tokens_details', {}).get('cached_tokens', 0)
        input_rate, cached_rate, output_rate = MODEL_RATES[self.model]
        cost = ((usage.get('input_tokens', 0) - cached) * input_rate +
                cached * cached_rate + usage.get('output_tokens', 0) * output_rate) / 1_000_000
        self.estimated_usd += cost
        output = data.get('output', [])
        raw = ''.join(c.get('text', '') for item in output for c in item.get('content', []) if c.get('type') == 'output_text')
        self.output = output
        self.last = {
            'model': self.model, 'raw_reply': raw, 'usage': usage, 'estimated_usd': cost,
            'latency_s': round(time.monotonic() - started, 2), 'status': data.get('status'),
            'reasoning_effort': effort or self.reasoning_effort,
            'context_mode': 'encrypted_replay' if carry else 'single_turn',
            'replayed_items': len(self.history) if carry else 0,
            'conversation_turns': self.turns + (1 if carry else 0),
            'tool_calls': [{'name': item.get('name'), 'call_id': item.get('call_id'), 'arguments': item.get('arguments')}
                           for item in output if item.get('type') == 'function_call']}
        if time.monotonic() >= self.deadline: raise RuntimeError('Mission deadline expired during API request')
        if data.get('status') != 'completed': raise RuntimeError('Model response incomplete; no action executed')
        if carry:
            normalized = []
            for item in output:
                item = dict(item)
                if item.get('type') == 'reasoning':
                    item.setdefault('summary', [])
                    if not item.get('encrypted_content'):
                        raise RuntimeError('Provider omitted encrypted reasoning; refusing silent continuity loss')
                normalized.append(item)
            self.history = context + normalized; self.turns += 1; self._save_session()
        return data, raw

    def ask(self, instruction, state, images=(), tokens=None, carry=True, reasoning_effort=None):
        return self._request(instruction, [self._message(state, images)], tokens, carry=carry, effort=reasoning_effort)[1]

    def respond(self, instruction, state, images=(), tools=(), tokens=None):
        return self._request(instruction, [self._message(state, images)], tokens, tools=list(tools))[0]

    def tool_result(self, instruction, call_id, result, images=(), tools=(), tokens=None):
        pending = {item.get('call_id') for item in self.history if item.get('type') == 'function_call'} - {
            item.get('call_id') for item in self.history if item.get('type') == 'function_call_output'}
        if call_id not in pending: raise ValueError('Unknown tool call; refusing unrelated output')
        items = [{'type': 'function_call_output', 'call_id': call_id, 'output': json.dumps(result)}]
        if images:
            items.append(self._message({'post_tool_images': 'Current observations after the verified tool result'}, images))
        return self._request(instruction, items, tokens, tools=list(tools))[0]

    def preflight(self):
        return self.ask('Reply only OK.', {'test': 'API access'}, tokens=128, carry=False, reasoning_effort='minimal')


def parse_object(raw):
    value = json.loads(raw)
    if not isinstance(value, dict): raise ValueError('Expected one JSON object')
    return value
