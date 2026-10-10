import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
import ai


class GatewayRefreshTests(unittest.TestCase):
    def failure(self, code=500, message=b'No healthy provider found in pool'):
        return HTTPError('http://127.0.0.1:3000/v1/chat/completions', code, 'error', {}, io.BytesIO(message))

    def test_refresh_rejection_retries_and_recovers(self):
        with patch('ai.urlopen', side_effect=[self.failure(), self.failure(), io.BytesIO(b'{"ok":true}')]) as request, patch('ai.time.sleep') as sleep:
            self.assertEqual(ai.request_json('http://127.0.0.1:3000/v1/chat/completions', {}), {'ok': True})
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_retries_are_bounded(self):
        with patch('ai.urlopen', side_effect=[self.failure() for _ in range(3)]) as request, patch('ai.time.sleep'):
            with self.assertRaises(HTTPError):
                ai.request_json('http://127.0.0.1:3000/v1/chat/completions', {})
        self.assertEqual(request.call_count, 3)

    def test_other_errors_and_remote_services_do_not_retry(self):
        for url, error in [('http://127.0.0.1:3000/v1/chat/completions', self.failure(401)),
                           ('http://127.0.0.1:3000/v1/chat/completions', self.failure(message=b'unknown server failure')),
                           ('https://api.example.com/chat/completions', self.failure())]:
            with self.subTest(url=url, code=error.code), patch('ai.urlopen', side_effect=error) as request, patch('ai.time.sleep') as sleep:
                with self.assertRaises(HTTPError):
                    ai.request_json(url, {})
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()
