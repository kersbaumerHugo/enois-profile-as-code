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
        config = {'username':'hugo-kersbaumer', 'api_base':'https://enois.ia.br/api'}
        result = deploy(config, {'bannerHtml':'same', 'bioHtml':'new'}, 'sess_test')
        self.assertTrue(result)
        method, url = http.call_args[0]
        self.assertEqual(method, 'PATCH')
        self.assertEqual(http.call_args.kwargs['body'], {'bioHtml':'new'})
        self.assertEqual(url, 'https://enois.ia.br/api/me/profile')

    @patch('scripts.enois_profile.public_profile')
    @patch('scripts.enois_profile.http_json')
    def test_deploy_rejects_wrong_account(self, http, public):
        http.return_value = {'id': 'user_wrong'}
        public.return_value = {'id': 'user_target'}
        config = {'username':'hugo-kersbaumer', 'api_base':'https://enois.ia.br/api'}
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
