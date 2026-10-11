import json, os, shutil, subprocess
from pathlib import Path


def az(*args):
    cli = shutil.which('az') or shutil.which('az.cmd')
    if not cli:
        raise RuntimeError('Installera Azure CLI och logga in först.')
    embedded = Path(cli).resolve().parent.parent/'python.exe'
    command = [str(embedded), '-X', 'utf8', '-IBm', 'azure.cli'] if embedded.exists() else [cli]
    run = subprocess.run(command+list(args), capture_output=True, encoding='utf-8',
        env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))
    if run.returncode:
        raise RuntimeError(run.stderr)
    return json.loads(run.stdout) if run.stdout.strip() else None
