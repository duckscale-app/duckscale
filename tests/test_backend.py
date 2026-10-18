import unittest
from unittest.mock import patch, MagicMock
from duckscale.backend import Client, DaemonError


class FakeClient(Client):
    def __init__(self):
        self.calls = []
        self.state = 'Stopped'
        self.profile = 'one'
        self.confirm = True

    def request(self, method, endpoint, data=None):
        self.calls.append((method, endpoint, data))
        if endpoint == 'prefs' and self.confirm:
            self.state = 'Running' if data['WantRunning'] else 'Stopped'
        if endpoint.startswith('profiles/') and method == 'POST' and self.confirm:
            self.profile = 'two'

    def snapshot(self):
        return {'BackendState': self.state}, {'ID': self.profile}, []


class ClientTests(unittest.TestCase):
    def test_toggle_preserves_other_preferences(self):
        client = FakeClient()
        self.assertEqual(client.set_enabled(True)[0]['BackendState'], 'Running')
        self.assertEqual(client.calls, [('PATCH', 'prefs',
                         {'WantRunning': True, 'WantRunningSet': True})])
        self.assertEqual(client.set_enabled(False)[0]['BackendState'], 'Stopped')

    def test_switch_confirms_account_without_overwriting_preferences(self):
        client = FakeClient()
        self.assertEqual(client.switch('two')[1]['ID'], 'two')
        self.assertEqual(client.calls, [('POST', 'profiles/two', None)])

    def test_unconfirmed_toggle_times_out(self):
        client = FakeClient()
        client.confirm = False
        with patch('duckscale.backend.time.monotonic', side_effect=[0, 1, 13]), \
             patch('duckscale.backend.time.sleep'):
            with self.assertRaisesRegex(DaemonError, 'did not reach'):
                client.set_enabled(True)

    def test_unconfirmed_switch_times_out(self):
        client = FakeClient()
        client.confirm = False
        with patch('duckscale.backend.time.monotonic', side_effect=[0, 1, 13]), \
             patch('duckscale.backend.time.sleep'):
            with self.assertRaisesRegex(DaemonError, 'did not confirm'):
                client.switch('two')

    def test_empty_profile_makes_no_request(self):
        client = FakeClient()
        with self.assertRaises(DaemonError):
            client.switch('')
        self.assertEqual(client.calls, [])

    def test_missing_socket_has_clear_error(self):
        with self.assertRaisesRegex(DaemonError, 'Cannot read Tailscale daemon'):
            Client('/tmp/duckscale-no-such-socket').snapshot()

    def test_permission_denied_and_connection_closed(self):
        with patch('duckscale.backend.UnixConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 403
            response.read.return_value = b'access denied'
            with self.assertRaisesRegex(DaemonError, 'operator'):
                Client().request('GET', 'status')
            connection.return_value.close.assert_called_once()

    def test_profile_id_is_url_encoded(self):
        client = FakeClient()
        with patch.object(client, 'wait'):
            client.switch('a/b?c')
        self.assertEqual(client.calls[0][1], 'profiles/a%2Fb%3Fc')


if __name__ == '__main__':
    unittest.main()

class LoginTests(unittest.TestCase):
    def client(self, status):
        client = Client()
        def request(method, endpoint, data=None):
            if method == 'GET' and endpoint == 'profiles/current':
                return {'ID': 'old'}
            if endpoint == 'status':
                return status
        client.request = MagicMock(side_effect=request)
        client.switch = MagicMock()
        return client

    def test_login_creates_separate_profile_before_authentication(self):
        client = self.client({'AuthURL': 'https://login.tailscale.com/a/test'})
        self.assertEqual(client.begin_login(), ('old', 'https://login.tailscale.com/a/test'))
        calls = [(c.args[0], c.args[1]) for c in client.request.call_args_list]
        self.assertEqual(calls, [('GET', 'profiles/current'), ('PUT', 'profiles/'),
                                 ('POST', 'login-interactive'), ('GET', 'status')])
        client.switch.assert_not_called()

    def test_unsafe_auth_url_restores_old_profile(self):
        client = self.client({'AuthURL': 'file:///etc/passwd'})
        with self.assertRaisesRegex(DaemonError, 'invalid sign-in URL'):
            client.begin_login()
        client.switch.assert_called_once_with('old')

    def test_missing_auth_url_times_out_and_restores_profile(self):
        client = self.client({})
        with patch('duckscale.backend.time.monotonic', side_effect=[0, 1, 16]), \
             patch('duckscale.backend.time.sleep'):
            with self.assertRaisesRegex(DaemonError, 'No sign-in link'):
                client.begin_login()
        client.switch.assert_called_once_with('old')

    def test_cancel_restores_saved_profile(self):
        client = self.client({})
        client.cancel_login('old')
        client.switch.assert_called_once_with('old')

class SettingsTests(unittest.TestCase):
    def client(self):
        client = Client()
        self.prefs = {'CorpDNS': True, 'RouteAll': False, 'WantRunning': True,
                      'ExitNodeID': 'keep-me'}
        def request(method, endpoint, data=None):
            if endpoint == 'profiles/current':
                return {'ID': 'one'}
            if endpoint == 'prefs':
                if method == 'PATCH':
                    self.prefs.update({k: v for k, v in data.items() if not k.endswith('Set')})
                return dict(self.prefs)
        client.request = MagicMock(side_effect=request)
        client.snapshot = MagicMock(return_value=({}, {'ID': 'one'}, []))
        return client

    def test_saves_only_selected_settings_with_masks(self):
        client = self.client()
        client.save_settings('one', {'CorpDNS': False, 'ShieldsUp': True})
        patch_call = [c for c in client.request.call_args_list if c.args[0] == 'PATCH'][0]
        self.assertEqual(patch_call.args[2], {'CorpDNS': False, 'ShieldsUp': True,
                                            'CorpDNSSet': True, 'ShieldsUpSet': True})
        self.assertTrue(self.prefs['WantRunning'])
        self.assertEqual(self.prefs['ExitNodeID'], 'keep-me')

    def test_account_changed_rejects_save(self):
        client = self.client()
        with self.assertRaisesRegex(DaemonError, 'Account changed'):
            client.save_settings('other', {'CorpDNS': False})
        self.assertFalse(any(c.args[0] == 'PATCH' for c in client.request.call_args_list))

    def test_unknown_setting_rejected(self):
        client = self.client()
        with self.assertRaisesRegex(DaemonError, 'Unsupported'):
            client.save_settings('one', {'WantRunning': False})

    def test_unconfirmed_preference_is_error(self):
        client = self.client()
        client.request.side_effect = lambda method, endpoint, data=None: (
            {'ID': 'one'} if endpoint == 'profiles/current' else {'CorpDNS': True})
        with self.assertRaisesRegex(DaemonError, 'did not confirm'):
            client.save_settings('one', {'CorpDNS': False})

class PermissionRecoveryTests(unittest.TestCase):
    def test_profile_denial_preserves_connection_status(self):
        from duckscale.backend import PermissionDenied
        client = Client()
        def request(method, endpoint, data=None):
            if endpoint == 'status':
                return {'BackendState': 'Running'}
            raise PermissionDenied('operator required')
        client.request = MagicMock(side_effect=request)
        status, current, profiles = client.snapshot()
        self.assertEqual(status['BackendState'], 'Running')
        self.assertEqual(status['ProfileError'], 'operator required')
        self.assertEqual((current, profiles), ({}, []))

    def test_status_failure_is_not_hidden_by_fallback(self):
        client = Client()
        client.request = MagicMock(side_effect=DaemonError('daemon unavailable'))
        with self.assertRaisesRegex(DaemonError, 'daemon unavailable'):
            client.snapshot()
