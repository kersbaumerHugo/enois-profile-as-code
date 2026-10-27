import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.enois_profile import (
    HTMLSafetyScanner, NoRedirect, ProfileError, changed_fields, deploy,
    read_local, sha,
)


class ProfileTests(unittest.TestCase):
    def test_project_files_pass_validation(self):
        config, html = read_local()
        self.assertEqual(config['username'], 'hugo-kersbaumer')
        self.assertEqual(set(html), {'bannerHtml', 'bioHtml'})

    def test_script_tag_forbidden(self):
        scanner = HTMLSafetyScanner()
        scanner.feed('<svg></svg><script>alert(1)</script>')
        self.assertTrue(scanner.errors)

    def test_event_handler_forbidden(self):
        scanner = HTMLSafetyScanner()
        scanner.feed('<div onclick="doSomething()">x</div>')
        self.assertTrue(scanner.errors)

    def test_javascript_url_forbidden(self):
        scanner = HTMLSafetyScanner()
        scanner.feed('<a href="java\nscript:alert(1)">x</a>')
        self.assertTrue(scanner.errors)

    def test_changes_are_minimal(self):
        local = {'bannerHtml': '<div>a</div>', 'bioHtml': '<div>b</div>'}
        remote = {'bannerHtml': '<div>a</div>', 'bioHtml': '<div>OLD</div>'}
        self.assertEqual(changed_fields(local, remote), {'bioHtml': '<div>b</div>'})

    def test_read_local_rejects_alternate_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'profile'
            p.mkdir()
            (p / 'config.json').write_text(json.dumps({'username': 'hugo-kersbaumer', 'api_base': 'http://example.com/api'}))
            (p / 'banner.html').write_text('<div>a</div>')
            (p / 'about.html').write_text('<div>b</div>')
            with self.assertRaises(ProfileError):
                read_local(Path(tmp))

    @patch('scripts.enois_profile.public_profile')
    @patch('scripts.enois_profile.http_json')
    def test_deploy_only_changed_fields_and_verifies(self, http, public):
        http.side_effect = [{'id': 'user_1'}, {'ok': True}]
        public.side_effect = [
            {'id': 'user_1', 'bannerHtml': 'same', 'bioHtml': 'old'},
            {'id': 'user_1', 'bannerHtml': 'same', 'bioHtml': 'new'},
        ]
        config = {'username':'hugo-kersbaumer', 'api_base':'https://enois.ia.br/api/v1', 'client_origin':'https://example.org'}
        result = deploy(config, {'bannerHtml':'same', 'bioHtml':'new'}, 'sess_test')
        self.assertTrue(result)
        method, url = http.call_args[0]
        self.assertEqual(method, 'PATCH')
        self.assertEqual(http.call_args.kwargs['body'], {'bioHtml':'new'})
        self.assertEqual(url, 'https://enois.ia.br/api/v1/me/profile')

    @patch('scripts.enois_profile.public_profile')
    @patch('scripts.enois_profile.http_json')
    def test_deploy_rejects_wrong_account(self, http, public):
        http.return_value = {'id': 'user_wrong'}
        public.return_value = {'id': 'user_target'}
        config = {'username':'hugo-kersbaumer', 'api_base':'https://enois.ia.br/api/v1', 'client_origin':'https://example.org'}
        with self.assertRaisesRegex(ProfileError, 'não pertence'):
            deploy(config, {'bannerHtml':'a', 'bioHtml':'b'}, 'sess_test')
        self.assertEqual(http.call_count, 1)

    def test_redirect_never_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "Moved", {}, "https://evil.example"))

    def test_hash_consistent(self):
        self.assertEqual(sha('test'), sha('test'))
        self.assertNotEqual(sha('test'), sha('TEST'))


if __name__ == '__main__':
    unittest.main()

class InteractiveAuthTests(unittest.TestCase):
    @patch('scripts.enois_profile.sys.stdin.isatty', return_value=True)
    @patch('scripts.enois_profile.getpass.getpass', side_effect=['very-secret', '123456'])
    @patch('builtins.input', return_value='hugo@example.com')
    @patch('scripts.enois_profile.http_json')
    @patch('scripts.enois_profile.client_origin', return_value='https://example.org')
    def test_2fa_login_does_not_persist_credentials(self, origin, http, inp, passwd, tty):
        from scripts.enois_profile import login_interactive
        http.side_effect = [(202, {'challengeId': 'ch_123'}), (200, {'token': 'sess_ABC', 'refreshToken': 'secret'})]
        config = {'api_base': 'https://enois.ia.br/api/v1'}
        self.assertEqual(login_interactive(config), 'sess_ABC')
        self.assertEqual(http.call_count, 2)
        self.assertEqual(http.call_args.kwargs['body'], {'challengeId': 'ch_123', 'code': '123456'})
        self.assertEqual(http.call_args[0], ('POST', 'https://enois.ia.br/api/v1/auth/2fa/verify'))

    @patch('scripts.enois_profile.sys.stdin.isatty', return_value=True)
    @patch('scripts.enois_profile.getpass.getpass', return_value='password')
    @patch('builtins.input', return_value='hugo@example.com')
    @patch('scripts.enois_profile.http_json', return_value=(202, {'unknown': 1}))
    @patch('scripts.enois_profile.client_origin', return_value='https://example.org')
    def test_unrecognized_2fa_challenge_fails_closed(self, origin, http, inp, passwd, tty):
        from scripts.enois_profile import login_interactive
        with self.assertRaisesRegex(ProfileError, 'challengeId'):
            login_interactive({'api_base': 'https://enois.ia.br/api/v1'})

    @patch('scripts.enois_profile.sys.stdin.isatty', return_value=False)
    @patch('scripts.enois_profile.client_origin', return_value='https://example.org')
    def test_cannot_login_in_ci(self, origin, tty):
        from scripts.enois_profile import login_interactive
        with self.assertRaisesRegex(ProfileError, 'TTY'):
            login_interactive({'api_base': 'https://enois.ia.br/api/v1'})

    @patch.dict('os.environ', {'ENOIS_CLIENT_ORIGIN': 'https://example.org'})
    def test_registered_origin_from_environment(self):
        from scripts.enois_profile import client_origin
        self.assertEqual(client_origin({}), 'https://example.org')

    @patch.dict('os.environ', {'ENOIS_CLIENT_ORIGIN': ''})
    def test_missing_origin_fails_before_request(self):
        from scripts.enois_profile import client_origin
        with self.assertRaisesRegex(ProfileError, 'Cadastre'):
            client_origin({'client_origin': ''})

    @patch('scripts.enois_profile.client_origin', return_value='https://example.org')
    @patch('scripts.enois_profile.http_json')
    def test_logout_uses_ephemeral_session(self, http, origin):
        from scripts.enois_profile import logout
        logout({'api_base': 'https://enois.ia.br/api/v1'}, 'sess_123')
        self.assertEqual(http.call_args.kwargs['token'], 'sess_123')

    @patch('scripts.enois_profile.client_origin', return_value='https://example.org')
    @patch('scripts.enois_profile.http_json')
    @patch('scripts.enois_profile.public_profile')
    def test_deploy_writes_v1_endpoint(self, public, http, origin):
        config = {'username': 'hugo-kersbaumer', 'api_base': 'https://enois.ia.br/api/v1'}
        http.side_effect = [{'id':'user_1'}, {'ok': True}]
        public.side_effect = [
            {'id': 'user_1', 'bannerHtml': 'old', 'bioHtml': 'same'},
            {'id': 'user_1', 'bannerHtml': 'new', 'bioHtml': 'same'},
        ]
        self.assertTrue(deploy(config, {'bannerHtml':'new', 'bioHtml':'same'}, 'sess_123'))
        self.assertEqual(http.call_args[0], ('PATCH', 'https://enois.ia.br/api/v1/me/profile'))
        self.assertEqual(http.call_args.kwargs['body'], {'bannerHtml':'new'})
