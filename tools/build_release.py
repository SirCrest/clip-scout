"""Build the standalone Windows release: dist/Clip-Scout-<version>-windows.zip (and a .sha256 beside it).

The zip holds one folder, `Clip Scout/`: the app as committed at HEAD (tests and tools are left out, see
.gitattributes) plus uv.exe, so nobody has to clone the repo or install anything first. Double-clicking
Clip Scout.bat in that folder sets up Python and the packages on the first run (a one-time download of a few GB),
then opens the app. The library is created inside the folder, so updating is extracting a newer zip over it.

Usage: uv run python tools/build_release.py [--uv PATH] [--allow-dirty]
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
FOLDER = 'Clip Scout'


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def version():
    """The version committed at HEAD, which is what the zip contains (not the working copy's)."""
    return tomllib.loads(git('show', 'HEAD:pyproject.toml'))['project']['version']


def check_windows_exe(uv):
    with open(uv, 'rb') as f:
        if f.read(2) != b'MZ':
            raise SystemExit(f'{uv} is not a Windows executable: pass --uv with a Windows uv.exe')


def uv_version(uv):
    """`uv --version` of the uv being bundled, which also proves it's a working Windows uv."""
    if sys.platform != 'win32':
        return 'uv (version not checked: built off Windows)'
    out = subprocess.run([str(uv), '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if 'windows' not in out:
        raise SystemExit(f'{uv} reports "{out}", not a Windows build')
    return out


def build(uv, out_dir=DIST, allow_dirty=False):
    if not allow_dirty and git('status', '--porcelain'):
        raise SystemExit('commit your changes first: the release is built from HEAD (or pass --allow-dirty)')
    uv = Path(uv)
    check_windows_exe(uv)
    bundled = uv_version(uv)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'Clip-Scout-{version()}-windows.zip'
    out.unlink(missing_ok=True)
    # git archive applies .gitattributes: export-ignore drops tests and tools, eol=crlf keeps the .bat runnable
    subprocess.run(['git', 'archive', '--format=zip', f'--prefix={FOLDER}/', '-o', str(out), 'HEAD'],
                   cwd=ROOT, check=True)
    with zipfile.ZipFile(out, 'a', zipfile.ZIP_DEFLATED) as z:
        z.write(uv, f'{FOLDER}/uv/uv.exe')
        z.writestr(f'{FOLDER}/VERSION.txt',
                   f'Clip Scout {version()} ({git("rev-parse", "--short", "HEAD")})\nbundled {bundled}\n')
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + '.sha256').write_text(f'{digest}  {out.name}\n', encoding='utf-8')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--uv', help='the uv.exe to bundle (default: the one on PATH)')
    p.add_argument('--allow-dirty', action='store_true', help='build even with uncommitted changes (HEAD is used)')
    args = p.parse_args()
    uv = args.uv or shutil.which('uv')
    if not uv:
        raise SystemExit('uv not found: pass --uv PATH')
    out = build(uv, allow_dirty=args.allow_dirty)
    print(f'{out} ({out.stat().st_size / 2**20:.0f} MB)')


if __name__ == '__main__':
    main()
