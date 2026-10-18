import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallTests(unittest.TestCase):
    def test_installs_launcher_menu_and_optional_autostart_with_space_in_path(self):
        with tempfile.TemporaryDirectory(prefix='duckscale install ') as home:
            env = dict(os.environ, HOME=home, XDG_DATA_HOME=home + '/data',
                       XDG_CONFIG_HOME=home + '/config')
            subprocess.run(['python3', 'scripts/install.py', '--autostart'],
                           env=env, check=True, capture_output=True)
            launcher = Path(home) / '.local/bin/duckscale'
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertIn(' --background', (Path(home) / 'config/autostart/duckscale.desktop').read_text())
            result = subprocess.run([str(launcher), '--help'], env=env,
                                    check=True, capture_output=True, text=True)
            self.assertIn('--socket', result.stdout)
