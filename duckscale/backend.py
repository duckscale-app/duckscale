"""Bounded HTTP over the existing tailscaled Unix socket."""
import getpass
import shlex
import http.client
import json
import socket
import subprocess
import time
from urllib.parse import quote


class DaemonError(RuntimeError):
    pass


class PermissionDenied(DaemonError):
    pass


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('local-tailscaled.sock', timeout=5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Client:
    def __init__(self, path='/var/run/tailscale/tailscaled.sock'):
        self.path = path

    def request(self, method, endpoint, data=None):
        connection = UnixConnection(self.path)
        try:
            connection.request(method, '/localapi/v0/' + endpoint,
                               None if data is None else json.dumps(data),
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read()
            if response.status == 403:
                raise PermissionDenied(
                    'Tailscale denied access. Run this once in a terminal, then refresh:\n'
                    + 'sudo tailscale set --operator=' + shlex.quote(getpass.getuser()))
            if not 200 <= response.status < 300:
                raise DaemonError(f'Tailscale HTTP {response.status}: {body.decode(errors="replace")[:300]}')
            return json.loads(body) if body else None
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise DaemonError(f'Cannot read Tailscale daemon: {exc}') from exc
        finally:
            connection.close()

    def _grant_operator(self):
        # Only called by explicit user actions, never by background refresh.
        command = ['/usr/bin/pkexec', '/usr/bin/tailscale', '--socket=' + self.path,
                   'set', '--operator=' + getpass.getuser()]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DaemonError('Could not authorize Tailscale controls. Use the operator command in a terminal.') from exc
        if result.returncode:
            raise DaemonError('Administrator authorization was cancelled or denied. No permission was granted.')

    def authorize_operator(self):
        self._grant_operator()
        return self.snapshot()

    def _ensure_operator(self):
        try:
            self.request('GET', 'profiles/current')
        except PermissionDenied:
            self._grant_operator()
            self.request('GET', 'profiles/current')

    def snapshot(self):
        status = self.request('GET', 'status')
        try:
            current = self.request('GET', 'profiles/current') or {}
            profiles = self.request('GET', 'profiles/') or []
        except PermissionDenied as exc:
            # Status is independently readable even without operator permission.
            status = dict(status, ProfileError=str(exc))
            current, profiles = {}, []
        return status, current, profiles

    def wait(self, predicate, message):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            snapshot = self.snapshot()
            if predicate(snapshot):
                return snapshot
            time.sleep(.25)
        raise DaemonError(message)

    def set_enabled(self, enabled):
        self.request('PATCH', 'prefs', {'WantRunning': enabled, 'WantRunningSet': True})
        target = 'Running' if enabled else 'Stopped'
        return self.wait(lambda s: s[0].get('BackendState') == target,
                         f'Tailscale did not reach {target}. Check login and network access.')

    def switch(self, profile_id):
        if not profile_id:
            raise DaemonError('No account selected.')
        self.request('POST', 'profiles/' + quote(profile_id, safe=''))
        self._ensure_operator()
        return self.wait(lambda s: s[1].get('ID') == profile_id,
                         'Tailscale did not confirm the selected account.')

    def begin_login(self):
        """Create a separate profile so existing account credentials are retained."""
        previous = self.request('GET', 'profiles/current').get('ID')
        self.request('PUT', 'profiles/')
        try:
            self._ensure_operator()
            self.request('POST', 'start', {})
            self.request('POST', 'login-interactive')
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                status = self.request('GET', 'status')
                url = status.get('AuthURL', '')
                if url:
                    from urllib.parse import urlsplit
                    parsed = urlsplit(url)
                    if parsed.scheme != 'https' or not parsed.hostname or parsed.username:
                        raise DaemonError('Tailscale supplied an invalid sign-in URL.')
                    return previous, url
                time.sleep(.25)
            raise DaemonError('No sign-in link received. Check your internet connection and retry.')
        except Exception as original:
            if previous:
                try:
                    self.switch(previous)
                except DaemonError:
                    raise DaemonError(str(original) + '\nTo return to your saved account, run: sudo tailscale switch ' + shlex.quote(previous)) from original
            raise

    def cancel_login(self, previous):
        if previous:
            return self.switch(previous)
        self.request('PUT', 'profiles/')
        return self.snapshot()

    def settings(self):
        current = self.request('GET', 'profiles/current')
        prefs = self.request('GET', 'prefs')
        if self.request('GET', 'profiles/current').get('ID') != current.get('ID'):
            raise DaemonError('Account changed while loading settings. Open settings again.')
        return current.get('ID'), prefs

    def save_settings(self, profile_id, changes):
        allowed = {'CorpDNS', 'RouteAll', 'ShieldsUp', 'ExitNodeAllowLANAccess'}
        if not profile_id or self.request('GET', 'profiles/current').get('ID') != profile_id:
            raise DaemonError('Account changed. Open settings again before saving.')
        if any(key not in allowed or type(value) is not bool for key, value in changes.items()):
            raise DaemonError('Unsupported settings change.')
        if changes:
            patch = dict(changes)
            patch.update({key + 'Set': True for key in changes})
            self.request('PATCH', 'prefs', patch)
            confirmed = self.request('GET', 'prefs')
            if any(confirmed.get(key) != value for key, value in changes.items()):
                raise DaemonError('Tailscale did not confirm the new settings. Reopen settings to check.')
        return self.snapshot()
