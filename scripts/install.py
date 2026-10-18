#!/usr/bin/env python3
"""Install for the current user; never requires sudo."""
import argparse
import os
from pathlib import Path
import shlex
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--autostart', action='store_true', help='Also start in the tray at login')
args = parser.parse_args()
source = Path(__file__).resolve().parent.parent
home = Path.home()
data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))
config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
dest = data / 'duckscale'
dest.mkdir(parents=True, exist_ok=True)
for directory in ('duckscale', 'assets'):
    shutil.copytree(source / directory, dest / directory, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
launcher = home / '.local/bin/duckscale'
launcher.parent.mkdir(parents=True, exist_ok=True)
launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(dest)) + '\nexec /usr/bin/python3 -m duckscale "$@"\n')
launcher.chmod(0o755)
# Desktop entry escaping differs from shell escaping.
def desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
entry = '[Desktop Entry]\nType=Application\nName=Duckscale\nComment=Manage your Tailscale connection and accounts\nExec=' + desktop_quote(launcher) + '\nIcon=' + str(dest / 'assets/logo.png') + '\nTerminal=false\nCategories=Network;\nStartupNotify=true\n'
applications = data / 'applications'
applications.mkdir(parents=True, exist_ok=True)
(applications / 'duckscale.desktop').write_text(entry)
if args.autostart:
    autostart = config / 'autostart'
    autostart.mkdir(parents=True, exist_ok=True)
    (autostart / 'duckscale.desktop').write_text(entry.replace('\nExec=' + desktop_quote(launcher), '\nExec=' + desktop_quote(launcher) + ' --background'))
print('Installed:', launcher)
print('Open Duckscale from your application menu.')
