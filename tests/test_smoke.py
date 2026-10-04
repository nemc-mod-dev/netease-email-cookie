#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Smoke tests for the cleaned-up service layer.

Run: python -m unittest discover -s tests -v
These tests never touch the network; responses are stubbed.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.storage_service import StorageService
from services.verify_service import VerifyService, _normalize_login_1351


class FakeResponse:
    def __init__(self, payload, status_code=200, text=None, content_type='application/json'):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)
        self.headers = {'content-type': content_type}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response):
        self._response = response

    def post(self, *args, **kwargs):
        return self._response


def verify_service(payload, **kwargs):
    return VerifyService(FakeSession(FakeResponse(payload, **kwargs)))


class VerifyServiceTest(unittest.TestCase):
    def test_submit_success_is_resolved(self):
        result = verify_service({'user': {'token': 'T', 'id': '1'}}).submit_verification_result('tk', '1234')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['verify_state'], 'verify_resolved')
        self.assertEqual(result['user_info']['token'], 'T')

    def test_check_status_pending_1351(self):
        result = verify_service({'code': 1351, 'reason': 'not yet'}).check_verification_status('tk')
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['verify_state'], 'verify_pending')

    def test_check_status_falls_back_to_manual_on_non_json(self):
        result = verify_service(None, text='<html>waf</html>', content_type='text/html').check_verification_status('tk')
        self.assertEqual(result['status'], 'manual_required')
        self.assertEqual(result['verify_state'], 'verify_manual_only')

    def test_send_sms_success(self):
        result = verify_service({'code': 200}).send_sms_code('tk')
        self.assertEqual(result['status'], 'success')

    def test_login_1351_normalizes_to_need_verify(self):
        result = _normalize_login_1351({'code': 1351}, {'verify_url': 'https://x/?ticket=a', 'ticket': 'a', 'code': '1'})
        self.assertEqual(result['status'], 'need_verify')
        self.assertEqual(result['verify_state'], 'verify_required')
        self.assertEqual(result['ticket'], 'a')


class StorageServiceTest(unittest.TestCase):
    def test_all_artifacts_are_written_under_artifacts_dir(self):
        with tempfile.TemporaryDirectory() as base:
            storage = StorageService(base)
            artifacts = storage.save_current_artifacts(
                {'sdkuid': 'u', 'sessionid': 's', 'deviceid': 'd', 'udid': 'x'},
                {'c': '1'},
                'a@163.com',
            )
            expected_dir = os.path.join(base, 'artifacts')
            for result in artifacts.values():
                if result.get('path'):
                    self.assertTrue(result['path'].startswith(expected_dir), result['path'])
            nemc_path = artifacts['export_cookie']['nemc']['path']
            self.assertIn(os.path.join('artifacts', 'nemc_cookie_'), nemc_path)

    def test_restore_reads_back_saved_session(self):
        with tempfile.TemporaryDirectory() as base:
            storage = StorageService(base)
            storage.save_current_artifacts(
                {'sdkuid': 'u', 'sessionid': 's', 'deviceid': 'd', 'udid': 'x'},
                {'c': '1'},
                'a@163.com',
            )
            snapshot = storage.restore_session_snapshot()
            self.assertTrue(snapshot['has_sauth'])
            self.assertTrue(snapshot['has_cookies'])
            self.assertEqual(snapshot['sauth']['sessionid'], 's')


if __name__ == '__main__':
    unittest.main()
