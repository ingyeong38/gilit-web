"""네트워크 없이 OAuth 프록시의 양방향 헤더·본문 전달을 검증한다."""
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('serve_frontend', Path(__file__).parents[1] / 'serve_frontend.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class AuthProxyTest(unittest.TestCase):
    def handler(self, method='GET', path='/api/auth/google/start'):
        handler = object.__new__(server.Handler)
        handler.command, handler.path = method, path
        handler.headers = {'Host': 'localhost:8000', 'Cookie': 'gilit_session=test-session',
                           'Origin': 'http://localhost:8000', 'Content-Type': 'application/json',
                           'Content-Length': '2'}
        handler.rfile, handler.wfile = io.BytesIO(b'{}'), io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        return handler

    def test_start_callback_me_and_logout_preserve_contract(self):
        for method, path, status in [('GET', '/api/auth/google/start', 302),
                                     ('GET', '/api/auth/kakao/callback?code=test&state=test', 302),
                                     ('GET', '/api/auth/me', 200), ('POST', '/api/auth/logout', 204)]:
            with self.subTest(path=path):
                handler = self.handler(method, path)
                response = Mock(status=status)
                response.read.return_value = b''
                response.getheaders.return_value = [
                    ('Location', '/pages/search.html?auth_result=success'),
                    ('Set-Cookie', 'gilit_session=test; HttpOnly; SameSite=Lax'),
                    ('Set-Cookie', 'gilit_oauth=; Max-Age=0; Path=/api/auth'),
                    ('Content-Type', 'application/json'), ('Connection', 'keep-alive')]
                conn = Mock()
                conn.getresponse.return_value = response
                with patch.object(server.http.client, 'HTTPConnection', return_value=conn):
                    handler.proxy_api()
                args, kwargs = conn.request.call_args
                self.assertEqual(args, (method, path))
                self.assertEqual(kwargs['body'], b'{}')
                for name in ('Host', 'Origin', 'Cookie', 'Content-Type'):
                    self.assertEqual(kwargs['headers'][name], handler.headers[name])
                sent = handler.send_header.call_args_list
                self.assertEqual(sum(call.args[0] == 'Set-Cookie' for call in sent), 2)
                self.assertTrue(any(call.args[0] == 'Location' for call in sent))
                self.assertFalse(any(call.args[0] == 'Connection' for call in sent))
                conn.close.assert_called_once()

    def test_callback_log_redacts_code_and_state(self):
        handler = self.handler(path='/api/auth/google/callback?code=secret&state=secret')
        with patch.object(server.SimpleHTTPRequestHandler, 'log_message') as log:
            handler.log_message('"%s" %s', 'GET ' + handler.path + ' HTTP/1.1', '302')
        self.assertNotIn('secret', str(log.call_args))
        self.assertIn('[REDACTED]', str(log.call_args))


if __name__ == '__main__':
    unittest.main()
