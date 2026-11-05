import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from brain import Brain


def reply(text='OK',status='completed',index=1):
    response=Mock();response.ok=True
    response.json.return_value={'status':status,'output':[
        {'type':'reasoning','id':f'rs_{index}','summary':[],'encrypted_content':f'opaque-test-{index}'},
        {'type':'message','role':'assistant','id':f'msg_{index}','content':[{'type':'output_text','text':text}]}],
        'usage':{'input_tokens':10,'output_tokens':10}}
    return response


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.environment=patch.dict(os.environ,{'META_MODEL_API_KEY':'unit-test-key'});self.environment.start()
    def tearDown(self):self.environment.stop()

    def test_replays_full_context_and_opaque_reasoning_without_server_storage(self):
        with patch('brain.requests.post',side_effect=[reply(index=1),reply(index=2)]) as post:
            brain=Brain();brain.ask('test',{'first':'already scanned 45 and 75'})
            brain.ask('test',{'second':'what was scanned?'})
            payload=post.call_args.kwargs['json']
            self.assertFalse(payload['store'])
            self.assertIn('reasoning.encrypted_content',payload['include'])
            self.assertEqual(payload['input'][0]['content'][0]['text'],json.dumps({'first':'already scanned 45 and 75'}))
            self.assertEqual(payload['input'][1]['encrypted_content'],'opaque-test-1')
            self.assertEqual(brain.turns,2)

    def test_private_session_survives_client_restart(self):
        with tempfile.TemporaryDirectory() as folder,patch('brain.requests.post',side_effect=[reply(index=1),reply(index=2)]) as post:
            path=Path(folder)/'conversation.json'
            brain=Brain(session_path=path);brain.ask('test',{'goal':'green mat'})
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            resumed=Brain(session_path=path);resumed.ask('test',{'question':'what goal?'})
            self.assertGreater(resumed.last['replayed_items'],0)
            self.assertEqual(resumed.turns,2)

    def test_preflight_is_not_added_to_mission_context(self):
        with patch('brain.requests.post',return_value=reply()):
            brain=Brain();brain.preflight()
            self.assertEqual(brain.history,[]);self.assertEqual(brain.turns,0)

    def test_incomplete_response_does_not_commit_a_turn(self):
        with patch('brain.requests.post',return_value=reply(status='incomplete')):
            brain=Brain()
            with self.assertRaises(RuntimeError):brain.ask('test',{})
            self.assertEqual(brain.history,[])

    def test_unknown_tool_output_rejected(self):
        brain=Brain()
        with self.assertRaises(ValueError):brain.tool_result('test','not-pending',{})

    def test_model_choice_is_sent_and_session_cannot_cross_models(self):
        with tempfile.TemporaryDirectory() as folder,patch('brain.requests.post',return_value=reply()) as post:
            path=Path(folder)/'conversation.json'
            brain=Brain(model='muse-spark-1.3',session_path=path)
            brain.ask('test',{'request':'hello'})
            self.assertEqual(post.call_args.kwargs['json']['model'],'muse-spark-1.3')
            self.assertEqual(json.loads(path.read_text())['model'],'muse-spark-1.3')
            with self.assertRaises(ValueError):Brain(model='muse-wonder-1.0',session_path=path)

if __name__=='__main__':unittest.main()
