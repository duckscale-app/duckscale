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
        self.settings_open = False
        self.login_pending = False
        self.previous_profile = None
        self.login_url = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.pending_operation = None
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
        self.settings_button = Gtk.Button.new_from_icon_name('preferences-system-symbolic', Gtk.IconSize.BUTTON)
        self.settings_button.set_tooltip_text('Connection settings')
        self.settings_button.connect('clicked', lambda *_: self.open_settings())
        header.pack_start(self.settings_button)
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
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(32)
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
        self.authorize_button = Gtk.Button(label='Authorize Tailscale controls…')
        self.authorize_button.connect('clicked', lambda *_: self.run_operation(
            self.client.authorize_operator, 'Waiting for administrator authorization…'))
        box.pack_start(self.authorize_button, False, False, 0)
        refresh = Gtk.Button(label='Refresh')
        refresh.connect('clicked', lambda *_: self.refresh())
        box.pack_start(refresh, False, False, 0)
        self.tray()
        self.window.show_all()
        self.login_box.hide()
        self.authorize_button.hide()
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
        self.tray_settings = Gtk.MenuItem(label='Settings…')
        self.tray_settings.connect('activate', lambda *_: self.open_settings())
        menu.append(self.tray_settings)
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
        for widget in (self.toggle, self.accounts, self.switch_button, self.add_button, self.login_box, self.settings_button, self.authorize_button):
            widget.set_sensitive(sensitive)
        if self.indicator:
            self.tray_toggle.set_sensitive(sensitive)
            self.account_menu.set_sensitive(sensitive)
            self.tray_add.set_sensitive(sensitive)
            self.tray_settings.set_sensitive(sensitive)

    def run_operation(self, operation, label=None, on_success=None):
        if self.busy:
            if label and self.pending_operation is None:
                self.pending_operation = (operation, label, on_success)
                self.controls(False)
            return
        self.busy = True
        if label:
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
            recovering = self.snapshot is None or bool(self.snapshot[0].get('ProfileError'))
            result = future.result()
            if on_success:
                on_success(result)
                return False
            self.snapshot = result
            self.render()
            if mutation or recovering:
                self.error.set_text(self.snapshot[0].get('ProfileError', ''))
        except Exception as exc:
            if mutation and self.snapshot is not None:
                # A rejected write does not imply loss of daemon/status access.
                self.render()
            else:
                self.snapshot = None
                self.status.set_text('Tailscale unavailable')
                self.detail.set_text('Check that tailscaled is running, then refresh.')
                self.accounts.remove_all()
                self.toggle.set_label('Enable Tailscale')
                self.controls(False)
            self.error.set_text(str(exc))
        finally:
            if self.pending_operation is not None:
                pending, self.pending_operation = self.pending_operation, None
                GLib.idle_add(self.run_operation, *pending)
        return False

    def render(self):
        status, current, profiles = self.snapshot
        state = status.get('BackendState', 'Unknown')
        profile_error = status.get('ProfileError', '')
        self.authorize_button.set_visible(bool(profile_error))
        self.authorize_button.set_sensitive(True)
        if profile_error:
            self.error.set_text(profile_error)
        if self.login_pending and current.get('ID'):
            self.login_pending = False
            self.login_url = None
            self.previous_profile = None
            self.login_box.hide()
        current = next((p for p in profiles if p.get('ID') == current.get('ID')), current)
        user = current.get('UserProfile') or {}
        account = user.get('LoginName') or current.get('Name')
        if not account:
            local_user = (status.get('User') or {}).get(str((status.get('Self') or {}).get('UserID')), {})
            account = local_user.get('LoginName') or ('Account access restricted' if profile_error else 'No account signed in')
        self.detail.set_text('Finish signing in in your browser, or cancel to return.' if self.login_pending else account)
        self.status.set_text({'Running': 'Connected', 'Stopped': 'Disabled',
                              'NeedsLogin': 'Sign-in required',
                              'Starting': 'Connecting…'}.get(state, state))
        self.controls(state in ('Running', 'Stopped') and not self.login_pending)
        self.add_button.set_sensitive(not self.login_pending and not profile_error)
        self.settings_button.set_sensitive(bool(current.get('ID')) and not self.login_pending)
        if self.indicator:
            self.tray_settings.set_sensitive(bool(current.get('ID')) and not self.login_pending)
        self.accounts.set_sensitive(not self.login_pending and not profile_error)
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
            self.tray_add.set_sensitive(not self.login_pending and not profile_error)
            self.account_menu.set_submenu(submenu)
            submenu.show_all()

    def open_settings(self):
        if self.login_pending or self.settings_open:
            return
        self.run_operation(self.client.settings, 'Loading settings…', self.show_settings)

    def show_settings(self, result):
        profile_id, prefs = result
        self.settings_open = True
        dialog = Gtk.Dialog(title='Connection settings', transient_for=self.window,
                            modal=True, destroy_with_parent=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dialog.add_button('Save changes', Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(20)
        content.set_spacing(14)
        controls = {}
        options = (
            ('CorpDNS', 'Use Tailscale DNS', 'Use the DNS configuration provided by this tailnet.', False),
            ('RouteAll', 'Accept subnet routes', 'Reach networks advertised by your tailnet’s subnet routers.', False),
            ('ShieldsUp', 'Allow incoming connections', 'Allow tailnet connections permitted by your access policy and local firewall.', True),
            ('ExitNodeAllowLANAccess', 'Allow local network with an exit node', 'Keep direct access to your LAN while using an exit node.', False),
        )
        for key, title, description, inverse in options:
            check = Gtk.CheckButton(label=title)
            check.set_active(not prefs.get(key, False) if inverse else prefs.get(key, False))
            content.pack_start(check, False, False, 0)
            hint = Gtk.Label(label=description, xalign=0, wrap=True)
            hint.set_max_width_chars(48)
            hint.get_style_context().add_class('hint')
            content.pack_start(hint, False, False, 0)
            controls[key] = (check, inverse)
        dialog.show_all()
        response = dialog.run()
        changes = {key: (not check.get_active() if inverse else check.get_active())
                   for key, (check, inverse) in controls.items()}
        changes = {key: value for key, value in changes.items() if value != prefs.get(key, False)}
        dialog.destroy()
        self.settings_open = False
        if response == Gtk.ResponseType.OK and changes:
            self.run_operation(lambda: self.client.save_settings(profile_id, changes), 'Saving settings…')
        else:
            self.refresh()

    def add_account(self):
        if self.login_pending or self.settings_open:
            self.window.present()
            return
        self.settings_open = True
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text='Sign in to another account?')
        dialog.format_secondary_text('Your connection will pause during sign-in. Linux may ask you to authorize Tailscale controls for the new profile. Cancel sign-in to return to the previous account.')
        response = dialog.run()
        dialog.destroy()
        self.settings_open = False
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
        if self.settings_open:
            return True
        self.run_operation(self.client.snapshot)
        return True

    def toggle_connection(self):
        if self.login_pending or self.settings_open:
            return
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
    parser.add_argument('--version', action='version', version='Duckscale 0.1.1')
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
