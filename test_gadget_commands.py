import contextlib,io,json,runpy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import gadget_command
from register_commands import definitions


class GadgetTests(unittest.TestCase):
    def test_registered_commands_exclude_retired_locate(self):
        commands=definitions(Path('/example/r1d1'))
        self.assertEqual(set(commands),{'r1d1.inspect','r1d1.memory','r1d1.acknowledge','r1d1.status','r1d1.stop'})
        self.assertTrue(all('target_approach.py' not in ' '.join(command['exec']) for command in commands.values()))

    def test_stop_command_still_latches_without_serial_access(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(gadget_command,'__file__',str(Path(folder)/'gadget_command.py')), \
             patch('sys.argv',['gadget_command.py','stop']),patch('sys.stdin',io.StringIO('{}')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            gadget_command.main()
            self.assertTrue((Path(folder)/'runtime/STOP').exists())
            self.assertTrue(json.loads(output.getvalue())['latched'])

    def test_registration_removes_only_the_retired_definition(self):
        with patch('subprocess.run') as run,contextlib.redirect_stdout(io.StringIO()):
            runpy.run_module('register_commands',run_name='__main__')
        removals=[call.args[0] for call in run.call_args_list if 'rm' in call.args[0]]
        self.assertEqual(removals,[['sudo','-n','rm','-f','--','/etc/musegadget/commands.d/r1d1.locate.json']])
