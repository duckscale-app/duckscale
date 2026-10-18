"""GTK desktop window with an optional AppIndicator tray."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gio, GLib, Gtk, Gdk, GdkPixbuf
from .backend import Client


class Duckscale(Gtk.Application):
    def __init__(self, client, start_hidden=False):
        super().__init__(application_id='app.duckscale.Duckscale')
        self.client = client
        self.start_hidden = start_hidden
        self.login_pending = False
        self.previous_profile = None
        self.login_url = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.snapshot = None
        self.indicator = None
        self.connect('activate', self.activate)

    def activate(self, *_):
        if hasattr(self, 'window'):
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='Duckscale')
        self.window.set_default_size(480, 460)
        self.window.set_resizable(False)
        header = Gtk.HeaderBar(title='Duckscale', subtitle='Your tailnets, within reach')
        header.set_show_close_button(True)
        self.window.set_titlebar(header)
        self.spinner = Gtk.Spinner()
        header.pack_end(self.spinner)
        css = Gtk.CssProvider()
        css.load_from_data(b'.connection { font-size: 26px; font-weight: bold; } .section { font-weight: bold; } .hint { opacity: 0.75; } button { padding: 9px 14px; }')
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.set_border_width(24)
        self.window.connect('delete-event', self.hide_window)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.window.add(box)
        logo = Path(__file__).resolve().parent.parent / 'assets' / 'logo.png'
        if logo.exists():
            self.window.set_icon_from_file(str(logo))
            image = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(logo), 88, 88, True))
            box.pack_start(image, False, False, 0)
        self.status = Gtk.Label(label='Reading Tailscale…', xalign=0)
        self.status.get_style_context().add_class('connection')
        box.pack_start(self.status, False, False, 0)
        self.toggle = Gtk.Button(label='Enable Tailscale')
        self.toggle.connect('clicked', lambda *_: self.toggle_connection())
        box.pack_start(self.toggle, False, False, 0)
        self.detail = Gtk.Label(label='Checking your connection', xalign=0, wrap=True)
        self.detail.get_style_context().add_class('hint')
        box.pack_start(self.detail, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 5)
        heading = Gtk.Label(label='Accounts', xalign=0)
        heading.get_style_context().add_class('section')
        box.pack_start(heading, False, False, 0)
        self.accounts = Gtk.ComboBoxText()
        box.pack_start(self.accounts, False, False, 0)
        self.switch_button = Gtk.Button(label='Switch account')
        self.switch_button.connect('clicked', lambda *_: self.switch_account())
        box.pack_start(self.switch_button, False, False, 0)
        self.add_button = Gtk.Button(label='Add account…')
        self.add_button.connect('clicked', lambda *_: self.add_account())
        box.pack_start(self.add_button, False, False, 0)
        self.login_box = Gtk.Box(spacing=8)
        self.reopen = Gtk.Button(label='Open sign-in page')
        self.reopen.connect('clicked', lambda *_: self.open_login())
        self.login_box.pack_start(self.reopen, True, True, 0)
        cancel = Gtk.Button(label='Cancel sign-in')
        cancel.connect('clicked', lambda *_: self.cancel_login())
        self.login_box.pack_start(cancel, True, True, 0)
        box.pack_start(self.login_box, False, False, 0)
        self.error = Gtk.Label(xalign=0, selectable=True, wrap=True)
        self.error.set_max_width_chars(52)
        box.pack_start(self.error, False, False, 0)
        refresh = Gtk.Button(label='Refresh')
        refresh.connect('clicked', lambda *_: self.refresh())
        box.pack_start(refresh, False, False, 0)
        self.tray()
        self.window.show_all()
        self.login_box.hide()
        if self.start_hidden and self.indicator:
            self.window.hide()
        self.refresh()
        GLib.timeout_add_seconds(3, self.refresh)

    def tray(self):
        try:
            gi.require_version('AyatanaAppIndicator3', '0.1')
            from gi.repository import AyatanaAppIndicator3 as Indicator
        except (ImportError, ValueError):
            return
        icon = str(Path(__file__).resolve().parent.parent / 'assets' / 'logo.png')
        self.indicator = Indicator.Indicator.new('duckscale', icon,
                                                Indicator.IndicatorCategory.COMMUNICATIONS)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        self.tray_toggle = Gtk.MenuItem(label='Reading Tailscale…')
        self.tray_toggle.connect('activate', lambda *_: self.toggle_connection())
        menu.append(self.tray_toggle)
        self.account_menu = Gtk.MenuItem(label='Accounts')
        menu.append(self.account_menu)
        self.tray_add = Gtk.MenuItem(label='Add account…')
        self.tray_add.connect('activate', lambda *_: self.add_account())
        menu.append(self.tray_add)
        show = Gtk.MenuItem(label='Open Duckscale')
        show.connect('activate', lambda *_: self.window.present())
        menu.append(show)
        quit_item = Gtk.MenuItem(label='Quit Duckscale')
        quit_item.connect('activate', lambda *_: self.quit())
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)

    def hide_window(self, *_):
        if self.indicator:
            self.window.hide()
            return True
        return False

    def controls(self, sensitive):
        for widget in (self.toggle, self.accounts, self.switch_button, self.add_button, self.login_box):
            widget.set_sensitive(sensitive)
        if self.indicator:
            self.tray_toggle.set_sensitive(sensitive)
            self.account_menu.set_sensitive(sensitive)
            self.tray_add.set_sensitive(sensitive)

    def run_operation(self, operation, label=None, on_success=None):
        if self.busy:
            return
        self.busy = True
        self.controls(False)
        self.spinner.start()
        if label:
            self.status.set_text(label)
        future = self.pool.submit(operation)
        future.add_done_callback(lambda f: GLib.idle_add(self.finish, f, label is not None, on_success))

    def finish(self, future, mutation, on_success=None):
        self.busy = False
        self.spinner.stop()
        try:
            recovering = self.snapshot is None
            result = future.result()
            if on_success:
                on_success(result)
                return False
            self.snapshot = result
            self.render()
            if mutation or recovering:
                self.error.set_text('')
        except Exception as exc:
            self.snapshot = None
            self.status.set_text('State unavailable — refresh to retry')
            self.error.set_text(str(exc))
            self.controls(False)
        return False

    def render(self):
        status, current, profiles = self.snapshot
        state = status.get('BackendState', 'Unknown')
        if self.login_pending and current.get('ID'):
            self.login_pending = False
            self.login_url = None
            self.previous_profile = None
            self.login_box.hide()
        current = next((p for p in profiles if p.get('ID') == current.get('ID')), current)
        user = current.get('UserProfile') or {}
        account = user.get('LoginName') or current.get('Name') or 'No account signed in'
        self.detail.set_text('Finish signing in in your browser, or cancel to return.' if self.login_pending else account)
        self.status.set_text({'Running': 'Connected', 'Stopped': 'Disabled',
                              'NeedsLogin': 'Sign-in required',
                              'Starting': 'Connecting…'}.get(state, state))
        self.controls(state in ('Running', 'Stopped') and not self.login_pending)
        self.add_button.set_sensitive(not self.login_pending)
        self.accounts.set_sensitive(not self.login_pending)
        self.login_box.set_sensitive(True)
        if self.indicator:
            self.tray_toggle.set_sensitive(state in ('Running', 'Stopped') and not self.login_pending)
        self.switch_button.set_sensitive(bool(profiles) and not self.login_pending)
        label = 'Disable Tailscale' if state == 'Running' else 'Enable Tailscale'
        self.toggle.set_label(label)
        previous = self.accounts.get_active_id()
        self.accounts.remove_all()
        submenu = Gtk.Menu() if self.indicator else None
        for profile in profiles:
            pid = profile.get('ID', '')
            user = profile.get('UserProfile') or {}
            name = user.get('LoginName') or profile.get('Name') or pid
            text = ('● ' if pid == current.get('ID') else '') + name
            self.accounts.append(pid, text)
            if submenu is not None:
                item = Gtk.MenuItem(label=text)
                item.connect('activate', lambda _, p=pid: self.switch_account(p))
                submenu.append(item)
        ids = {p.get('ID') for p in profiles}
        self.accounts.set_active_id(previous if previous in ids else current.get('ID', ''))
        if self.indicator:
            self.tray_toggle.set_label(label if state in ('Running', 'Stopped') else state)
            self.account_menu.set_sensitive(bool(profiles) and not self.login_pending)
            self.tray_add.set_sensitive(not self.login_pending)
            self.account_menu.set_submenu(submenu)
            submenu.show_all()

    def add_account(self):
        if self.busy or self.login_pending:
            self.window.present()
            return
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text='Sign in to another account?')
        dialog.format_secondary_text('Your current connection will pause during sign-in. Cancel sign-in to return to your previous account.')
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.run_operation(self.client.begin_login, 'Preparing sign-in…', self.login_ready)

    def login_ready(self, result):
        self.previous_profile, self.login_url = result
        self.login_pending = True
        self.login_box.show_all()
        self.window.present()
        self.open_login()
        self.refresh()

    def open_login(self):
        if self.login_url:
            try:
                Gio.AppInfo.launch_default_for_uri(self.login_url, None)
            except GLib.Error:
                self.error.set_text('Could not open your browser. Install a default browser, then select Open sign-in page.')

    def cancel_login(self):
        def restored(snapshot):
            self.login_pending = False
            self.login_url = None
            self.previous_profile = None
            self.login_box.hide()
            self.snapshot = snapshot
            self.render()
            self.error.set_text('')
        if self.busy or not self.login_pending:
            return
        self.run_operation(lambda: self.client.cancel_login(self.previous_profile),
                           'Returning to previous account…', restored)

    def refresh(self):
        self.run_operation(self.client.snapshot)
        return True

    def toggle_connection(self):
        if self.snapshot:
            enabled = self.snapshot[0].get('BackendState') != 'Running'
            self.run_operation(lambda: self.client.set_enabled(enabled),
                               'Connecting…' if enabled else 'Disconnecting…')

    def switch_account(self, profile_id=None):
        selected = profile_id or self.accounts.get_active_id()
        if selected:
            self.run_operation(lambda: self.client.switch(selected), 'Switching account…')


def main():
    parser = argparse.ArgumentParser(description='Duckscale desktop controller')
    parser.add_argument('--version', action='version', version='Duckscale 0.1.0')
    parser.add_argument('--background', action='store_true', help='Start in the tray')
    parser.add_argument('--socket', default='/var/run/tailscale/tailscaled.sock')
    args = parser.parse_args()
    app = Duckscale(Client(args.socket), args.background)
    try:
        app.run([])
    finally:
        app.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
