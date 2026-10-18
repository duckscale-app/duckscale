"""Run with xvfb-run; only fake daemon state is changed."""
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gdk, Gio
from unittest.mock import patch
from duckscale.__main__ import Duckscale
from test_backend import FakeClient


class DemoClient(FakeClient):
    def snapshot(self):
        profiles = [{'ID': 'one', 'Name': 'Personal'}, {'ID': 'two', 'Name': 'Work'}]
        return {'BackendState': self.state}, {'ID': self.profile}, profiles

    def begin_login(self):
        previous = self.profile
        self.profile = ''
        return previous, 'https://login.tailscale.com/a/fake'

    def cancel_login(self, previous):
        self.profile = previous
        return self.snapshot()


app = Duckscale(DemoClient())
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
step = 0
failed = []


def check():
    global step
    if app.busy or not hasattr(app, 'toggle'):
        return True
    try:
        if step == 0:
            assert app.status.get_text() == 'Disabled'
            app.toggle_connection()
        elif step == 1:
            assert app.status.get_text() == 'Connected'
            app.switch_account('two')
        elif step == 2:
            assert app.snapshot[1]['ID'] == 'two'
            app.toggle_connection()
        elif step == 3:
            assert app.status.get_text() == 'Disabled'
            app.run_operation(app.client.begin_login, 'Preparing sign-in…', app.login_ready)
        elif step == 4:
            assert app.login_pending
            assert app.login_box.get_visible()
            app.cancel_login()
        elif step == 5:
            assert not app.login_pending
            assert app.snapshot[1]['ID'] == 'two'
            app.run_operation(app.client.begin_login, 'Preparing sign-in…', app.login_ready)
        elif step == 6:
            assert app.login_pending
            app.client.profile = 'one'
            app.client.state = 'Running'
            app.refresh()
        else:
            assert not app.login_pending
            assert app.status.get_text() == 'Connected'
            assert app.detail.get_text() == 'Personal'
            window = app.window.get_window()
            pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, app.window.get_allocated_width(), app.window.get_allocated_height())
            pixbuf.savev('/tmp/duckscale-ui.png', 'png', [], [])
            app.quit()
            return False
        step += 1
    except Exception as exc:
        failed.append(exc)
        app.quit()
        return False
    return True


def timeout():
    failed.append(RuntimeError('UI smoke test timed out'))
    app.quit()
    return False


GLib.timeout_add(100, check)
GLib.timeout_add_seconds(10, timeout)
with patch('duckscale.__main__.Gio.AppInfo.launch_default_for_uri', return_value=True):
    app.run([])
app.pool.shutdown()
if failed:
    raise failed[0]
assert step == 7
print('GTK smoke passed: toggle, switch, add-account browser handoff, cancel/restore, login completion')
