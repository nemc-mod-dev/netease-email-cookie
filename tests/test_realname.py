#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""离线测试：实名接口封装与批量编排（全部使用桩对象，不联网）。"""

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.batch_service import BatchRealnameRunner
from services.realname_service import (
    REALNAME_REQUIRED,
    REALNAME_UNKNOWN,
    REALNAME_VERIFIED,
    RealnameService,
    classify_realname,
    mask_id_num,
    mask_realname,
    validate_id_num,
)


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
    def __init__(self, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        return self.get_response

    def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        return self.post_response


def build_service(session):
    device = {'game_id': 'aecfrxodyqaaaajp-g-x19', 'device_id': 'dev1'}
    return RealnameService(
        session,
        app_payload_getter=lambda: {'game_id': device['game_id'], 'cv': 'a5.16.0'},
        headers_getter=lambda: {'Content-Type': 'application/x-www-form-urlencoded'},
        device_info_getter=lambda: device,
    )


class ClassifyTest(unittest.TestCase):
    def test_status_zero_is_required(self):
        state, detail = classify_realname({'realname_status': 0, 'need_aas': True})
        self.assertEqual(state, REALNAME_REQUIRED)
        self.assertTrue(detail['need_aas'])

    def test_status_one_is_verified(self):
        state, _ = classify_realname({'realname_status': 1})
        self.assertEqual(state, REALNAME_VERIFIED)

    def test_unknown_value_is_unknown(self):
        state, _ = classify_realname({'realname_status': 7})
        self.assertEqual(state, REALNAME_UNKNOWN)

    def test_missing_user_is_unknown(self):
        self.assertEqual(classify_realname(None)[0], REALNAME_UNKNOWN)


class IdentityTest(unittest.TestCase):
    def test_valid_id_num(self):
        self.assertTrue(validate_id_num('110101199001011237')[0])
        self.assertTrue(validate_id_num('110101900101123')[0])

    def test_bad_checksum(self):
        ok, reason = validate_id_num('110101199001011234')
        self.assertFalse(ok)
        self.assertIn('校验位', reason)

    def test_mask_helpers(self):
        self.assertEqual(mask_realname('张三'), '张*')
        self.assertEqual(mask_realname('欧阳娜娜'), '欧**娜')
        self.assertEqual(mask_id_num('110101199001011237'), '110***********1237')


class RealnameServiceTest(unittest.TestCase):
    def test_query_status_needs_realname(self):
        session = FakeSession(get_response=FakeResponse({'user': {'realname_status': 0, 'need_aas': True, 'refill_realname_flag': 0}}))
        result = build_service(session).query_status('uid', 'token')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['realname_state'], REALNAME_REQUIRED)
        self.assertTrue(result['needs_realname'])
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, 'GET')
        self.assertTrue(url.endswith('/devices/dev1/users/uid/info'))
        self.assertEqual(kwargs['params']['opt_fields'], 'realname_status')
        self.assertEqual(kwargs['params']['token'], 'token')

    def test_query_status_falls_back_on_bad_json(self):
        session = FakeSession(get_response=FakeResponse(ValueError('bad json'), text='<html>', content_type='text/html'))
        result = build_service(session).query_status('uid', 'token')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['realname_state'], REALNAME_UNKNOWN)

    def test_submit_calls_verify_then_update(self):
        session = FakeSession(post_response=FakeResponse({'need_aas': False, 'realname_type': '成年人'}))
        result = build_service(session).submit('uid', 'token', '张三', '110101199001011237')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['sync_status'], 'success')
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.calls[0][1].endswith('/realname/verify'))
        self.assertTrue(session.calls[1][1].endswith('/realname/update_by_token'))
        body = session.calls[0][2]['data']
        self.assertEqual(body['user_id'], 'uid')
        self.assertEqual(body['id_region'], '86')
        self.assertEqual(body['realname'], '张三')

    def test_submit_rejects_bad_identity(self):
        session = FakeSession(post_response=FakeResponse({}))
        result = build_service(session).submit('uid', 'token', '张三', '123')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(session.calls, [])


class FakeAuth:
    def __init__(self, storage, initial_state=REALNAME_REQUIRED):
        self.storage = storage
        self.device_id = 'dev1'
        self.device_key = 'key1'
        self.udid = 'udid1'
        self.device_info = {'device_id': 'dev1', 'unique_id': 'uniq1', 'game_id': 'aecfrxodyqaaaajp-g-x19'}
        self.sauth_data = {}
        self.session = types.SimpleNamespace(cookies={})
        self._state = initial_state
        self.submitted = []

    def inject_session(self, sauth, cookies=None):
        self.sauth_data = dict(sauth)
        return {'status': 'success'}

    def prepare_device(self):
        return {'status': 'success'}

    def check_realname_status(self):
        return {
            'status': 'success',
            'realname_state': self._state,
            'needs_realname': self._state == REALNAME_REQUIRED,
            'need_aas': self._state == REALNAME_REQUIRED,
            'refill_realname_flag': 0,
        }

    def submit_realname(self, realname, id_num, id_region='86', sync=True):
        self.submitted.append((realname, id_num))
        self._state = REALNAME_VERIFIED
        return {'status': 'success', 'message': '实名提交成功', 'need_aas': False, 'realname_type': '成年人'}


PROVIDED_SESSION = {'sdkuid': 'uid', 'sessionid': 'sess', 'deviceid': 'dev1', 'udid': 'udid1'}


class AuthServiceIntegrationTest(unittest.TestCase):
    """真实 NetEaseAuthService + 桩网络，验证封装链路。"""

    def test_check_and_submit_realname_through_auth_service(self):
        from services.auth_service import NetEaseAuthService
        from services.storage_service import StorageService

        with tempfile.TemporaryDirectory() as base:
            auth = NetEaseAuthService(storage=StorageService(base))
            auth.inject_session(PROVIDED_SESSION)

            calls = []

            def fake_get(url, **kwargs):
                calls.append(('GET', url))
                return FakeResponse({'user': {'realname_status': 0, 'need_aas': True, 'refill_realname_flag': 0}})

            def fake_post(url, **kwargs):
                calls.append(('POST', url))
                return FakeResponse({'need_aas': False, 'realname_type': '成年人'})

            auth.session.get = fake_get
            auth.session.post = fake_post

            review = auth.check_realname_status()
            self.assertEqual(review['realname_state'], REALNAME_REQUIRED)
            self.assertTrue(review['needs_realname'])

            submitted = auth.submit_realname('张三', '110101199001011237')
            self.assertEqual(submitted['status'], 'success')
            self.assertEqual([c[0] for c in calls], ['GET', 'POST', 'POST'])
            self.assertTrue(calls[0][1].endswith('/users/uid/info'))
            self.assertTrue(calls[1][1].endswith('/realname/verify'))


class BatchRunnerTest(unittest.TestCase):
    def test_review_only_does_not_submit(self):
        with tempfile.TemporaryDirectory() as base:
            runner = BatchRealnameRunner(output_root=base, auth_factory=FakeAuth, sleeper=lambda s: None)
            account = {'label': 'a@163.com', 'identifier': 'a@163.com', 'sauth': PROVIDED_SESSION,
                       'realname': '张三', 'id_num': '110101199001011237'}
            report = runner.run([account], submit=False)
            result = report['results'][0]
            self.assertEqual(result['stage'], 'reviewed')
            self.assertTrue(result['needs_realname'])
            self.assertIsNone(result['submit_status'])
            self.assertEqual(report['summary']['required'], 1)
            self.assertTrue(os.path.exists(report['report_json']))
            self.assertTrue(os.path.exists(report['report_csv']))

    def test_submit_and_confirm(self):
        with tempfile.TemporaryDirectory() as base:
            runner = BatchRealnameRunner(output_root=base, auth_factory=FakeAuth, sleeper=lambda s: None)
            account = {'label': 'a@163.com', 'identifier': 'a@163.com', 'sauth': PROVIDED_SESSION,
                       'realname': '张三', 'id_num': '110101199001011237'}
            report = runner.run([account], submit=True)
            result = report['results'][0]
            self.assertEqual(result['submit_status'], 'success')
            self.assertEqual(result['confirmed_state'], REALNAME_VERIFIED)
            self.assertEqual(report['summary']['submitted'], 1)
            # 报告中不得出现完整证件号
            blob = json.dumps(report, ensure_ascii=False)
            self.assertNotIn('110101199001011237', blob)
            self.assertIn('110***********1237', blob)

    def test_missing_identity_is_skipped(self):
        with tempfile.TemporaryDirectory() as base:
            runner = BatchRealnameRunner(output_root=base, auth_factory=FakeAuth, sleeper=lambda s: None)
            account = {'label': 'b@163.com', 'identifier': 'b@163.com', 'sauth': PROVIDED_SESSION}
            report = runner.run([account], submit=True)
            self.assertEqual(report['results'][0]['submit_status'], 'skipped')
            self.assertEqual(report['summary']['skipped'], 1)

    def test_session_reused_from_file(self):
        with tempfile.TemporaryDirectory() as base:
            sauth_file = os.path.join(base, 'nemc.json')
            with open(sauth_file, 'w', encoding='utf-8') as f:
                json.dump({'sauth_json': json.dumps(PROVIDED_SESSION)}, f)
            runner = BatchRealnameRunner(output_root=os.path.join(base, 'out'), auth_factory=FakeAuth, sleeper=lambda s: None)
            account = {'label': 'c@163.com', 'identifier': 'c@163.com', 'sauth_file': sauth_file}
            report = runner.run([account], submit=False)
            self.assertEqual(report['results'][0]['session_source'], 'provided')
            self.assertEqual(report['results'][0]['stage'], 'reviewed')


if __name__ == '__main__':
    unittest.main()
