"""Run the retained D7 configuration in a fresh workspace; never overwrite runs."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / 'v2-d7'
D7 = HERE / 'd7'
RUNTIME = ROOT.parent / '.experiment-env'
SHORT = Path('/private/tmp/cs5231-env-validation')

def load(path):
    return json.loads(path.read_text())

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def snapshot(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and not p.is_symlink()}

def verify():
    lock = load(D7 / 'input-lock.json')
    for relative, expected in lock['files_sha256'].items():
        if sha(ROOT / relative) != expected:
            raise ValueError('D7 input changed: ' + relative)
    if sha(D7 / 'protocol.json') != lock['protocol_sha256']:
        raise ValueError('Formal protocol changed')
    if sha(OUT / 'capture/protocol.json') != lock['collection_protocol_sha256']:
        raise ValueError('Collection-time protocol changed')
    return load(D7 / 'protocol.json')

def sandbox_profile(workspace):
    """Instantiate the same intended boundary for this checkout and user."""
    paths = {'__WORKSPACE__': str(workspace), '__RUNTIME__': str(RUNTIME),
             '__TEMP__': str(SHORT / 'tmp'), '__HOME__': str(Path.home())}
    ancestors = {parent for path in (ROOT, RUNTIME, workspace) for parent in path.parents}
    ancestors.add(ROOT)
    text = (D7 / 'sandbox-template.sb').read_text()
    for marker, path in paths.items():
        text = text.replace(marker, path.replace('\\', '\\\\').replace('"', '\\"'))
    literals = ' '.join('(literal ' + json.dumps(str(path)) + ')' for path in sorted(ancestors))
    return text.replace('__ANCESTORS__', literals)

def run_one(name, scenario):
    protocol = verify()
    if not re.fullmatch(r'run-\d{3,}', name):
        raise ValueError('Use run-NNN')
    run = SHORT / name
    archive = ROOT / 'artifact/runs' / name
    profile = RUNTIME / ('d7-' + name + '.sb')
    if any(p.exists() for p in (run, archive, profile, OUT / (name + '-environment.json'))):
        raise ValueError('Existing run or evidence; never relaunch or overwrite')
    policy = Path(protocol['execution_policy_path'])
    policy.parent.mkdir(parents=True, exist_ok=True)
    if policy.exists() and sha(policy) != protocol['execution_policy_sha256']:
        raise ValueError('Existing policy differs')
    if not policy.exists():
        shutil.copy2(D7 / 'execution-policy-d7.txt', policy)
    config = RUNTIME / 'd7.json'
    if config.exists() and sha(config) != protocol['config_sha256']:
        raise ValueError('Existing D7 runtime config differs')
    if not config.exists():
        shutil.copy2(D7 / 'config-d7.json', config)
    (SHORT / 'tmp').mkdir(exist_ok=True)
    subprocess.run([sys.executable, '-B', str(ROOT / 'artifact/scripts/prepare.py'),
                    scenario, '--output', str(run)], check=True)
    if load(run / 'baseline.json') != protocol['baseline_by_condition'][scenario]:
        raise ValueError('Initial scenario differs from D7 protocol')
    if sha(run / 'prompt.txt') != protocol['prompt_sha256']:
        raise ValueError('Task differs from D7 protocol')
    profile.write_text(sandbox_profile(run / 'workspace'))
    env = os.environ.copy()
    env.update(TMPPREFIX=str(SHORT / 'tmp/zsh'), OPENCODE_CONFIG=str(config),
               CS5231_AGENT_SANDBOX_PROFILE=str(profile))
    record = {'run': name, 'scenario': scenario, 'model': protocol['model'],
              'state': 'running', 'started_at': datetime.now(ZoneInfo('Asia/Singapore')).isoformat(),
              'actual_run_directory': str(run), 'sandbox_sha256': sha(profile),
              'configuration': protocol['configuration'],
              'note': 'Additional D7 run; excluded from fixed 030-039 formal denominators.'}
    save(OUT / (name + '-environment.json'), record)
    command = [sys.executable, '-B', str(D7 / 'controlled_collect.py'), str(run),
               '--model', protocol['model'], '--timeout', '600', '--max-segments', '4']
    with (OUT / (name + '-collector.log')).open('w') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        record['collector_pid'] = process.pid
        save(OUT / (name + '-environment.json'), record)
        code = process.wait()
    with (OUT / (name + '-check.log')).open('w') as log:
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'artifact/scripts/check.py'), str(run)],
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode not in (0, 1) or not (run / 'check.json').is_file():
        raise ValueError('Check failed; preserve scene and inspect, do not relaunch')
    shutil.copytree(run, archive)
    if snapshot(run) != snapshot(archive):
        raise ValueError('Archive differs')
    save(OUT / (name + '-archive-hashes.json'), snapshot(archive))
    record.update(state='finished', collector_returncode=code,
                  checks_passed=sum(c['passed'] for c in load(run / 'check.json')['checks']))
    save(OUT / (name + '-environment.json'), record)
    print(json.dumps(record, ensure_ascii=False))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('verify')
    launch = sub.add_parser('run')
    launch.add_argument('name')
    launch.add_argument('--scenario', required=True, choices=['normal', 'documentation-injection'])
    args = parser.parse_args()
    if args.action == 'verify':
        verify()
        print('D7 inputs and formal protocol verified; no model launched.')
    else:
        run_one(args.name, args.scenario)
