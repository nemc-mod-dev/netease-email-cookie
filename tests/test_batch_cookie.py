#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""批量转 Cookie 编排的离线测试（桩对象，不联网）。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.batch_service import BatchCookieRunner


class FakeCookieAuth:
    def __init__(self, storage):
        self.storage = storage
        self.device_id = 'dev1'
        self.device_key = 'key1'
        self.udid = 'udid1'
        self.device_info = {'device_id': 'dev1', 'unique_id': 'uniq1'}
        self.last_artifacts = {}
        self.session = None

    def prepare_device(self):
        return {'status': 'success'}

    def login_email(self, email, password):
        self.last_artifacts = {'export_cookie': {'nemc': {'path': f'/tmp/{email}.json'}}}
        return {'status': 'success', 'message': '登录成功'}

    def save_all_artifacts(self, label):
        self.last_artifacts = {'export_cookie': {'nemc': {'path': f'/tmp/{label}.json'}}}
        return {'status': 'success'}

    def inject_session(self, sauth, cookies=None):
        return {'status': 'success'}


class FakeVerifyAuth(FakeCookieAuth):
    def login_email(self, email, password):
        return {'status': 'need_verify', 'message': '需要安全验证',
                'ticket': 'TK123', 'verify_url': 'https://example/verify?ticket=TK123'}


class CookieRunnerTest(unittest.TestCase):
    def test_successful_conversion(self):
        with tempfile.TemporaryDirectory() as base:
            runner = BatchCookieRunner(output_root=base, auth_factory=FakeCookieAuth, sleeper=lambda s: None)
            report = runner.run([{'identifier': 'a@163.com', 'password': 'pw', 'label': 'a@163.com'}])
            self.assertEqual(report['kind'], 'cookie')
            self.assertEqual(report['summary']['ready'], 1)
            result = report['results'][0]
            self.assertEqual(result['stage'], 'cookie_ready')
            self.assertEqual(result['nemc_path'], '/tmp/a@163.com.json')
            self.assertTrue(os.path.exists(report['report_json']))
            self.assertTrue(os.path.exists(report['report_csv']))

    def test_missing_password_fails_fast(self):
        with tempfile.TemporaryDirectory() as base:
            runner = BatchCookieRunner(output_root=base, auth_factory=FakeCookieAuth, sleeper=lambda s: None)
            report = runner.run([{'identifier': 'a@163.com'}])
            self.assertEqual(report['results'][0]['stage'], 'missing_password')
            self.assertEqual(report['summary']['failed'], 1)

    def test_1351_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as base:
            runner = BatchCookieRunner(output_root=base, auth_factory=FakeVerifyAuth, sleeper=lambda s: None)
            report = runner.run([{'identifier': 'a@163.com', 'password': 'pw'}])
            result = report['results'][0]
            self.assertEqual(result['stage'], 'needs_manual_verify')
            self.assertEqual(result['ticket'], 'TK123')
            self.assertEqual(report['summary']['needs_manual_verify'], 1)
            self.assertEqual(report['summary']['failed'], 0)
            self.assertTrue(os.path.exists(report['needs_verify_json']))
            with open(report['needs_verify_json'], encoding='utf-8') as f:
                manual = json.load(f)
            self.assertEqual(manual[0]['ticket'], 'TK123')

    def test_shared_device_reused_across_accounts(self):
        with tempfile.TemporaryDirectory() as base:
            created = []

            class TrackingAuth(FakeCookieAuth):
                def __init__(self, storage):
                    super().__init__(storage)
                    created.append(storage)

            runner = BatchCookieRunner(output_root=base, auth_factory=TrackingAuth, sleeper=lambda s: None)
            runner.run([{'identifier': 'a@163.com', 'password': 'p'},
                        {'identifier': 'b@163.com', 'password': 'q'}])
            self.assertEqual(len(created), 2)


if __name__ == '__main__':
    unittest.main()
