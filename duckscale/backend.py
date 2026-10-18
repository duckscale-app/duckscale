"""Bounded HTTP over the existing tailscaled Unix socket."""
import http.client
import json
import socket
import time
from urllib.parse import quote


class DaemonError(RuntimeError):
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
                raise DaemonError('Permission denied. Configure your user as a Tailscale operator; see README.')
            if not 200 <= response.status < 300:
                raise DaemonError(f'Tailscale HTTP {response.status}: {body.decode(errors="replace")[:300]}')
            return json.loads(body) if body else None
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise DaemonError(f'Cannot read Tailscale daemon: {exc}') from exc
        finally:
            connection.close()

    def snapshot(self):
        return (self.request('GET', 'status'),
                self.request('GET', 'profiles/current'),
                self.request('GET', 'profiles/') or [])

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
        return self.wait(lambda s: s[1].get('ID') == profile_id,
                         'Tailscale did not confirm the selected account.')

    def begin_login(self):
        """Create a separate profile so existing account credentials are retained."""
        previous = self.request('GET', 'profiles/current').get('ID')
        self.request('PUT', 'profiles/')
        try:
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
        except Exception:
            if previous:
                self.switch(previous)
            raise

    def cancel_login(self, previous):
        if previous:
            return self.switch(previous)
        self.request('PUT', 'profiles/')
        return self.snapshot()
