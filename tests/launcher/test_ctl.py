"""Service controller lifecycle tests using DUMMY services (sleep scripts in
a temp dir) — no real engines, databases or ports are touched."""
import json
import os
import signal
import subprocess
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from launcher.paperbotctl import Controller, ServiceDef  # noqa: E402


def make_controller(tmp_path, crash=False, trap_int=True):
    script = tmp_path / 'dummy.sh'
    if crash:
        script.write_text("#!/bin/bash\nsleep 0.3\nexit 7\n")
    else:
        # graceful: exits 0 on SIGINT, like the real engines
        script.write_text("#!/bin/bash\ntrap 'exit 0' INT TERM\nwhile true; do sleep 0.2; done\n")
    script.chmod(0o755)
    svc = ServiceDef(key='dummy', name='Dummy Service',
                     cmd=[str(script)], cwd=str(tmp_path),
                     match=str(script),            # cmdline fingerprint
                     log=str(tmp_path / 'dummy.log'))
    ctl = Controller([svc], run_dir=str(tmp_path / 'run'))
    return ctl, svc, script


def test_start_status_stop_lifecycle(tmp_path):
    ctl, svc, _ = make_controller(tmp_path)
    assert ctl.status()['dummy']['state'] == 'stopped'
    assert ctl.start('dummy') is True
    time.sleep(0.3)
    st = ctl.status()['dummy']
    assert st['state'] == 'running' and st['pid'] > 0
    assert ctl.start('dummy') is False          # already running: no duplicate
    assert ctl.stop('dummy') is True
    time.sleep(0.2)
    assert ctl.status()['dummy']['state'] == 'stopped'
    assert not ctl._pidfile(svc).exists()


def test_adopts_externally_started_process(tmp_path):
    ctl, svc, script = make_controller(tmp_path)
    external = subprocess.Popen([str(script)])
    try:
        time.sleep(0.2)
        st = ctl.status()['dummy']
        assert st['state'] == 'running'
        assert st['adopted'] is True
        assert st['pid'] == external.pid
        assert ctl.start('dummy') is False      # recognised, not duplicated
        assert ctl.stop('dummy') is True        # graceful stop of adopted proc
        time.sleep(0.4)
        assert external.poll() is not None
    finally:
        if external.poll() is None:
            external.kill()


def test_never_kills_unmatched_processes(tmp_path):
    ctl, svc, _ = make_controller(tmp_path)
    bystander = subprocess.Popen(['sleep', '30'])
    try:
        # stale pidfile pointing at an UNRELATED process must be ignored
        ctl._pidfile(svc).parent.mkdir(parents=True, exist_ok=True)
        ctl._pidfile(svc).write_text(json.dumps({'pid': bystander.pid, 'cmd': 'x'}))
        assert ctl.status()['dummy']['state'] == 'stopped'
        ctl.stop('dummy')
        time.sleep(0.2)
        assert bystander.poll() is None         # untouched
    finally:
        bystander.kill()


def test_crash_detection_and_bounded_restarts(tmp_path):
    ctl, svc, _ = make_controller(tmp_path, crash=True)
    ctl.start('dummy')
    time.sleep(0.6)
    st = ctl.status()['dummy']
    assert st['state'] == 'failed'
    assert st['exit_code'] == 7
    # supervisor: restart up to max_restarts, then give up as failed
    for _ in range(10):
        ctl.supervise()
        time.sleep(0.5)
    st = ctl.status()['dummy']
    assert st['state'] == 'failed'
    assert ctl.restart_counts['dummy'] == ctl.max_restarts  # bounded, not infinite


def test_own_match_recognizes_title_rewriting_processes(tmp_path):
    """Processes like next-server rewrite their cmdline; a pid we started
    (pidfile) may be verified via own_match, but external adoption must stay
    strict so similar unrelated processes are never matched."""
    script = tmp_path / 'rename.sh'
    # exec a bash with a rewritten argv[0] to simulate a title rewrite
    script.write_text(
        "#!/bin/bash\nexec -a fake-server-title bash -c 'while :; do sleep 1; done'\n")
    script.chmod(0o755)
    svc = ServiceDef(key='web', name='Web', cmd=[str(script)], cwd=str(tmp_path),
                     match=str(script), own_match=['fake-server-title'],
                     log=str(tmp_path / 'web.log'))
    ctl = Controller([svc], run_dir=str(tmp_path / 'run'))
    ctl.start('web')
    time.sleep(0.5)
    st = ctl.status()['web']
    assert st['state'] == 'running' and st['adopted'] is False  # via pidfile+own_match
    # an EXTERNAL process with the same rewritten title is NOT adopted
    external = subprocess.Popen(
        ['bash', '-c', 'exec -a fake-server-title bash -c "while :; do sleep 1; done"'])
    try:
        time.sleep(0.3)
        assert ctl.status()['web']['duplicates'] == 0
        ctl.stop('web')
        time.sleep(0.5)
        assert external.poll() is None      # bystander with same title untouched
    finally:
        external.kill()


def test_logs_are_written_per_service(tmp_path):
    script = tmp_path / 'talker.sh'
    script.write_text("#!/bin/bash\necho hello-from-service\nsleep 5\n")
    script.chmod(0o755)
    svc = ServiceDef(key='talker', name='Talker', cmd=[str(script)],
                     cwd=str(tmp_path), match=str(script),
                     log=str(tmp_path / 'talker.log'))
    ctl = Controller([svc], run_dir=str(tmp_path / 'run'))
    ctl.start('talker')
    time.sleep(0.4)
    assert 'hello-from-service' in (tmp_path / 'talker.log').read_text()
    ctl.stop('talker')
