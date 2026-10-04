#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""纯控制台入口的离线测试（全部使用桩对象，不联网）。"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as console
from console_ui import format_status, summarize_result


class FakeAuth:
    def __init__(self):
        self.last_login_context = {}
        self.calls = []
        self._snapshot = {
            'device_id': 'dev1', 'device_key_present': True, 'sdkuid': 'uid',
            'sessionid_present': True, 'cookie_count': 3, 'restored_session': {'has_sauth': True},
            'current_conversion_complete': True, 'current_conversion_label': 'a@163.com',
        }

    def check_realname_status(self):
        return {'status': 'success', 'message': '实名状态查询成功', 'realname_state': 'required',
                'needs_realname': True, 'realname_status': 0, 'need_aas': True}

    def submit_realname(self, realname, id_num, id_region='86'):
        self.calls.append(('submit', realname, id_num, id_region))
        return {'status': 'success', 'message': '实名提交成功', 'need_aas': False, 'realname_type': '成年人'}

    def check_verification_status(self, ticket):
        return {'status': 'pending', 'verify_state': 'verify_pending'}

    def send_verify_sms(self, ticket):
        return {'status': 'success', 'message': '短信验证码已发送'}

    def export_restored_session(self, label):
        return {'status': 'success', 'message': '已导出', 'export_paths': ['artifacts/x.json']}

    def rebuild_device(self):
        return {'status': 'success', 'message': '设备信息上传成功'}

    def get_state_snapshot(self):
        return self._snapshot


class FakeWorkflow:
    def __init__(self, login_result):
        self.login_result = login_result
        self.calls = []

    def run_email_login(self, identifier, password):
        self.calls.append(('email', identifier, password))
        return self.login_result

    def request_phone_sms(self, phone):
        self.calls.append(('request_sms', phone))
        return {'status': 'success', 'message': '短信验证码已请求'}

    def complete_phone_login(self, phone, code):
        self.calls.append(('phone', phone, code))
        return self.login_result

    def confirm_verification(self, ticket, label):
        self.calls.append(('verify', ticket, label))
        return {'status': 'success', 'message': '验证确认成功'}

    def fetch_mailbox(self):
        return {'status': 'success', 'message': '邮箱列表获取成功'}


def make_app(login_result=None):
    login_result = login_result or {'status': 'success', 'message': '登录成功', 'artifacts': {}}
    return console.ConsoleApp(auth=FakeAuth(), workflow=FakeWorkflow(login_result))


def run(capture_output, func, *args, **kwargs):
    with redirect_stdout(capture_output):
        return func(*args, **kwargs)


class ParserTest(unittest.TestCase):
    def test_login_defaults(self):
        args = console.build_parser().parse_args(['login', '--identifier', 'a@163.com'])
        self.assertEqual(args.command, 'login')
        self.assertEqual(args.mode, 'email')
        self.assertEqual(args.timeout, 300)

    def test_short_verbose_flag(self):
        args = console.build_parser().parse_args(['realname-check', '-v'])
        self.assertTrue(args.verbose)

    def test_batch_realname_intercepted_without_args(self):
        # batch-realname 由 main() 拦截并透传；不带参数时给出用法
        out = io.StringIO()
        code = run(out, console.main, ['batch-realname'])
        self.assertEqual(code, 2)
        self.assertIn('accounts.json', out.getvalue())


class LoginCommandTest(unittest.TestCase):
    def test_email_login_success(self):
        app = make_app()
        args = console.build_parser().parse_args(['login', '--identifier', 'a@163.com', '--password', 'pw'])
        code = run(io.StringIO(), console.cmd_login, app, args)
        self.assertEqual(code, 0)
        self.assertEqual(app.workflow.calls, [('email', 'a@163.com', 'pw')])

    def test_need_verify_sets_pending_and_returns_3(self):
        app = make_app({'status': 'need_verify', 'message': '需要完成安全验证', 'ticket': 'TK', 'verify_url': 'https://v/?ticket=TK'})
        args = console.build_parser().parse_args(['login', '--identifier', 'a@163.com', '--password', 'pw'])
        out = io.StringIO()
        code = run(out, console.cmd_login, app, args)
        self.assertEqual(code, 3)
        self.assertEqual(app.pending_ticket, 'TK')
        self.assertIn('验证链接', out.getvalue())
        self.assertIn('TK', out.getvalue())

    def test_missing_identifier_non_interactive(self):
        app = make_app()
        args = console.build_parser().parse_args(['login'])
        code = run(io.StringIO(), console.cmd_login, app, args)
        self.assertEqual(code, 2)


class RealnameCommandTest(unittest.TestCase):
    def test_realname_check_reports_state(self):
        app = make_app()
        args = console.build_parser().parse_args(['realname-check'])
        out = io.StringIO()
        code = run(out, console.cmd_realname_check, app, args)
        self.assertEqual(code, 0)
        self.assertIn('需要实名', out.getvalue())

    def test_realname_submit_with_yes(self):
        app = make_app()
        args = console.build_parser().parse_args(
            ['realname-submit', '--realname', '张三', '--id-num', '110101199001011237', '--yes']
        )
        code = run(io.StringIO(), console.cmd_realname_submit, app, args)
        self.assertEqual(code, 0)
        self.assertEqual(app.auth.calls, [('submit', '张三', '110101199001011237', '86')])

    def test_realname_submit_bad_identity_requires_confirmation(self):
        app = make_app()
        args = console.build_parser().parse_args(['realname-submit', '--id-num', 'x', '--yes'])
        # 非交互且缺少 realname -> 返回 2，不应调用提交
        code = run(io.StringIO(), console.cmd_realname_submit, app, args)
        self.assertEqual(code, 2)
        self.assertEqual(app.auth.calls, [])


class MiscCommandTest(unittest.TestCase):
    def test_batch_without_args(self):
        app = make_app()
        args = console.build_parser().parse_args(['batch-realname'])
        code = run(io.StringIO(), console.cmd_batch_realname, app, args)
        self.assertEqual(code, 2)

    def test_export_and_status(self):
        app = make_app()
        args = console.build_parser().parse_args(['export'])
        self.assertEqual(run(io.StringIO(), console.cmd_export, app, args), 0)
        args = console.build_parser().parse_args(['status'])
        out = io.StringIO()
        self.assertEqual(run(out, console.cmd_status, app, args), 0)
        self.assertIn('设备ID: dev1', out.getvalue())


class ConsoleUiTest(unittest.TestCase):
    def test_summarize_result_marks_verify_link(self):
        lines = summarize_result({'status': 'need_verify', 'message': '需要完成安全验证',
                                  'verify_url': 'https://v/?ticket=TK', 'ticket': 'TK',
                                  'verify_state': 'verify_required'})
        blob = '\n'.join(lines)
        self.assertIn('验证链接', blob)
        self.assertIn('Ticket: TK', blob)

    def test_format_status(self):
        text = format_status(FakeAuth().get_state_snapshot())
        self.assertIn('会话(sessionid): 有效', text)
        self.assertIn('HTTP Cookies: 3 个', text)


if __name__ == '__main__':
    unittest.main()
