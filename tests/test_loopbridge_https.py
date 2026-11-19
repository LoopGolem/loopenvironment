# SPDX-License-Identifier: Apache-2.0
import socket
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from loopbridge.https_egress import Egress, connect, destinations, https_url, public_ip
from loopbridge.web_https import execute, field_value, WebError


class DestinationTests(unittest.TestCase):
    def test_exact_hostname_and_https_policy_rejects_private_urls(self):
        hosts = destinations(['example.com'])
        self.assertEqual(https_url('https://example.com/search?q=fake', hosts).netloc, 'example.com')
        for url in ('http://example.com/', 'https://example.com:443/', 'https://foo.example.com/',
                    'https://example.com@127.0.0.1/', 'https://example.com/%2561dmin/',
                    'https://example.com/wp-admin/', 'https://example.com\\@127.0.0.1/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                https_url(url, hosts)
        for host in ('localhost', '127.0.0.1', 'virtual.local', 'foo.internal', '*example.com'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                destinations([host])

    def test_non_public_answers_and_ipv6_transition_ranges_fail_closed(self):
        for address in ('127.0.0.1', '10.1.2.3', '100.64.0.1', '169.254.169.254', '224.0.0.1',
                        '::1', 'fd12::1', '::ffff:8.8.8.8', '2002:7f00:1::1', '64:ff9b::7f00:1'):
            self.assertFalse(public_ip(address), address)
        self.assertTrue(public_ip('1.1.1.1'))
        self.assertTrue(public_ip('2606:4700::1111'))
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (addr, 443))
                   for addr in ('1.1.1.1', '127.0.0.1')]
        with patch('loopbridge.https_egress.socket.getaddrinfo', return_value=answers), \
                patch('loopbridge.https_egress.socket.socket') as outgoing:
            with self.assertRaisesRegex(ValueError, 'non_public_dns_answer'):
                connect('example.com')
            outgoing.assert_not_called()

    def test_unix_proxy_denies_unknown_host_and_non_https_method(self):
        with tempfile.TemporaryDirectory() as folder:
            endpoint = Path(folder) / 'tls.sock'
            with Egress(endpoint, destinations(['example.com'])) as proxy:
                server = threading.Thread(target=proxy.serve_forever, daemon=True)
                server.start()
                try:
                    with patch('loopbridge.https_egress.connect') as outgoing:
                        for request in (b'CONNECT other.com:443 HTTP/1.1\r\n\r\n',
                                        b'CONNECT example.com:80 HTTP/1.1\r\n\r\n',
                                        b'GET / HTTP/1.1\r\n\r\n'):
                            with socket.socket(socket.AF_UNIX) as client:
                                client.connect(str(endpoint))
                                client.sendall(request)
                                self.assertIn(b'403 Forbidden', client.recv(1024))
                        outgoing.assert_not_called()
                    events = proxy.snapshot()
                    self.assertEqual([row['outcome'] for row in events],
                                     ['host_denied', 'request_denied', 'request_denied'])
                    self.assertNotEqual(events[0]['destination'], 'other.com')
                finally:
                    proxy.shutdown()
                    server.join(timeout=1)


class ExternalFormTests(unittest.TestCase):
    def test_typed_fields_have_a_bounded_native_contract(self):
        field_value('text', 'Portugal')
        field_value('date', '2027-02-12')
        with self.assertRaises(WebError):
            field_value('date', '2027-02-31')
        with self.assertRaises(WebError):
            field_value('password', 'irrelevant')

    @patch('loopbridge.web_https.snapshot')
    def test_normal_activate_cannot_dispatch_html_submit(self, snapshot):
        req = dict(document='doc', url='https://example.com/', key='button', role='button', name='Send')
        snapshot.return_value = {**req, 'controls': [{**req, 'kind': 'submit', 'required': True,
                                                      'valid': False, 'value': ''}]}
        with self.assertRaisesRegex(WebError, 'web_effect_requires_qualification'):
            execute(None, {**req, 'operation': 'external_activate'}, None)
        with self.assertRaisesRegex(WebError, 'web_required_field_invalid'):
            execute(None, {**req, 'operation': 'external_submit'}, None)
