"""Exercise real redirected streams with Windows-style legacy encodings."""
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
WRAP_STREAMS = '''
import io,sys
sys.stdout=io.TextIOWrapper(sys.stdout.buffer, encoding="cp1252", errors="strict")
sys.stderr=io.TextIOWrapper(sys.stderr.buffer, encoding="cp1252", errors="strict")
'''


def run_script(script):
    return subprocess.run([sys.executable, '-c', WRAP_STREAMS + script], cwd=str(ROOT),
                          capture_output=True, encoding='utf-8')


def test_unicode_recommendation_json_on_legacy_output_stream(tmp_path):
    args = ['--project', str(tmp_path), 'role', 'recommend', '--query', '小红书营销', '--library', 'agency']
    result = run_script('from agent_team.cli import main\nraise SystemExit(main(' + repr(args) + '))')
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['query'] == '小红书营销'
    assert payload['candidates'][0]['id'] == 'agency-marketing-xiaohongshu-specialist'
    assert '小红书营销' in result.stdout


def test_installer_unicode_destination_on_legacy_output_stream(tmp_path):
    destination = tmp_path / '中文技能'
    args = ['--destination', str(destination)]
    result = run_script('from agent_team.installer import main\nraise SystemExit(main(' + repr(args) + '))')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['path'] == str(destination.resolve())
    assert not destination.exists()


@pytest.mark.parametrize('entry', ['cli', 'installer', 'runner'])
def test_unicode_errors_are_utf8_json_on_legacy_stream(entry, tmp_path):
    if entry == 'cli':
        code = "from agent_team.cli import main\nargs=['--project', %r, 'status']\n" % str(tmp_path / '不存在')
    elif entry == 'installer':
        code = '''
import agent_team.installer as module
def unavailable(*args):
    raise OSError('中文错误')
module.export_bundle=unavailable
main=module.main
args=['--destination', %r, '--approve']
''' % str(tmp_path / '中文技能')
    else:
        path = ROOT / 'agent_team/skill/scripts/run.py'
        code = '''
import importlib.util
spec=importlib.util.spec_from_file_location('runner', %r)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def unavailable():
    raise ValueError('\u4e2d\u6587\u9519\u8bef')
module.locations=unavailable
main=module.main
args=[]
''' % str(path)
    result = run_script(code + '\nraise SystemExit(main(args))')
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stderr)
    assert any(ord(char) > 127 for char in payload['error'])
    assert 'UnicodeEncodeError' not in result.stderr


@pytest.mark.parametrize('entry', ['cli', 'installer', 'runner'])
def test_surrogate_filesystem_errors_remain_json(entry, tmp_path):
    # POSIX can expose undecodable filename bytes through surrogateescape.
    # Even those errors must not crash JSON error reporting after reconfigure.
    failure = "def unavailable(*args):\n    raise ValueError('filename-' + chr(0xdcff))\n"
    if entry == 'cli':
        code = 'import agent_team.cli as module\n' + failure
        code += "module.dispatch=unavailable\nargs=['--project', %r, 'status']\n" % str(tmp_path)
    elif entry == 'installer':
        code = 'import agent_team.installer as module\n' + failure
        code += "module.export_bundle=unavailable\nargs=['--destination', %r, '--approve']\n" % str(tmp_path / 'skill')
    else:
        code = '''
import importlib.util
spec=importlib.util.spec_from_file_location('runner', %r)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
''' % str(ROOT / 'agent_team/skill/scripts/run.py')
        code += failure + 'module.locations=unavailable\nargs=[]\n'
    result = run_script(code + '\nraise SystemExit(module.main(args))')
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stderr)['error'] == 'filename-' + chr(0xdcff)
    assert 'UnicodeEncodeError' not in result.stderr
