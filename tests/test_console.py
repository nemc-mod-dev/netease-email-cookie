#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""批量控制台入口的离线测试（注入桩 runner，不联网）。"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as console


class FakeRunner:
    def __init__(self, kind='cookie', summary=None):
        self.kind = kind
        self.calls = []
        self.summary = summary or {'total': 1, 'ready': 1, 'needs_manual_verify': 0, 'failed': 0}

    def run(self, accounts, delay=0.0, on_progress=None, submit=False):
        self.calls.append({'accounts': accounts, 'delay': delay, 'submit': submit})
        if on_progress:
            on_progress(1, len(accounts), {
                'index': 1, 'identifier': accounts[0].get('identifier', 'a'), 'label': 'a',
                'stage': 'cookie_ready', 'nemc_path': '/tmp/x.json',
            })
        return {
            'kind': self.kind, 'summary': self.summary, 'results': [],
            'report_json': 'r.json', 'report_csv': 'r.csv',
        }


def run(capture, func, *args, **kwargs):
    with redirect_stdout(capture):
        return func(*args, **kwargs)


def write_accounts(base, text='a@163.com----pw\nb@163.com----pw2\n'):
    path = os.path.join(base, 'accounts.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


class _StateMixin(unittest.TestCase):
    def setUp(self):
        console._CONFIG['accounts'] = None
        console._CONFIG['source'] = ''
        console._CONFIG['delay'] = 2.0


class ParserTest(unittest.TestCase):
    def test_cookies_defaults(self):
        args = console.build_parser().parse_args(['cookies', '--input', 'x.txt'])
        self.assertEqual(args.command, 'cookies')
        self.assertEqual(args.delay, 2.0)
        self.assertEqual(args.output, console.BATCH_OUTPUT_ROOT)

    def test_realname_submit_flag(self):
        args = console.build_parser().parse_args(['realname', '--input', 'x.txt', '--submit'])
        self.assertTrue(args.submit)

    def test_realname_defaults_to_review(self):
        args = console.build_parser().parse_args(['realname', '--input', 'x.txt'])
        self.assertFalse(args.submit)


class CookiesCommandTest(_StateMixin):
    def test_reads_file_and_runs(self):
        with tempfile.TemporaryDirectory() as base:
            path = write_accounts(base)
            runner = FakeRunner()
            args = console.build_parser().parse_args(['cookies', '--input', path, '--delay', '0'])
            out = io.StringIO()
            code = run(out, console.cmd_cookies, args, runner)
            self.assertEqual(code, 0)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(len(runner.calls[0]['accounts']), 2)
            self.assertIn('汇总', out.getvalue())

    def test_missing_input_non_interactive(self):
        with mock.patch.object(console, 'is_interactive', return_value=False):
            args = console.build_parser().parse_args(['cookies'])
            code = run(io.StringIO(), console.cmd_cookies, args, FakeRunner())
            self.assertEqual(code, 2)


class RealnameCommandTest(_StateMixin):
    def test_review_only(self):
        with tempfile.TemporaryDirectory() as base:
            path = write_accounts(base)
            runner = FakeRunner('realname', summary={'total': 2, 'verified': 1, 'required': 1,
                                                     'unknown': 0, 'needs_manual_verify': 0, 'failed': 0})
            args = console.build_parser().parse_args(['realname', '--input', path, '--delay', '0'])
            code = run(io.StringIO(), console.cmd_realname, args, runner)
            self.assertEqual(code, 0)
            self.assertFalse(runner.calls[0]['submit'])

    def test_submit_mode(self):
        with tempfile.TemporaryDirectory() as base:
            path = write_accounts(base)
            runner = FakeRunner('realname', summary={'total': 2, 'verified': 0, 'required': 2,
                                                     'unknown': 0, 'submitted': 2, 'submit_failed': 0,
                                                     'skipped': 0, 'needs_manual_verify': 0, 'failed': 0})
            args = console.build_parser().parse_args(['realname', '--input', path, '--delay', '0', '--submit'])
            code = run(io.StringIO(), console.cmd_realname, args, runner)
            self.assertEqual(code, 0)
            self.assertTrue(runner.calls[0]['submit'])


class ResultCommandTest(unittest.TestCase):
    def test_prints_latest_report(self):
        with tempfile.TemporaryDirectory() as base:
            run_dir = os.path.join(base, '20260101_000000')
            os.makedirs(run_dir)
            report = {'kind': 'cookie', 'generated_at': '2026-01-01 00:00:00',
                      'summary': {'total': 1, 'ready': 1, 'needs_manual_verify': 0, 'failed': 0},
                      'results': [], 'needs_manual_verify': []}
            with open(os.path.join(run_dir, 'report.json'), 'w', encoding='utf-8') as f:
                json.dump(report, f)
            args = console.build_parser().parse_args(['result', '--output', base])
            out = io.StringIO()
            code = run(out, console.cmd_result, args)
            self.assertEqual(code, 0)
            self.assertIn('20260101_000000', out.getvalue())

    def test_no_runs(self):
        with tempfile.TemporaryDirectory() as base:
            args = console.build_parser().parse_args(['result', '--output', base])
            code = run(io.StringIO(), console.cmd_result, args)
            self.assertEqual(code, 1)


class InteractiveGuardTest(unittest.TestCase):
    def test_non_interactive_prints_hint(self):
        with mock.patch.object(console, 'is_interactive', return_value=False):
            out = io.StringIO()
            code = run(out, console.run_interactive)
            self.assertEqual(code, 2)
            self.assertIn('非交互环境', out.getvalue())


class ConfigTest(_StateMixin):
    def test_set_delay_parses_number(self):
        with mock.patch.object(console, 'prompt', return_value='5'):
            run(io.StringIO(), console._set_delay)
        self.assertEqual(console._CONFIG['delay'], 5.0)

    def test_set_delay_keeps_value_on_garbage(self):
        console._CONFIG['delay'] = 3.0
        with mock.patch.object(console, 'prompt', return_value='abc'):
            run(io.StringIO(), console._set_delay)
        self.assertEqual(console._CONFIG['delay'], 3.0)

    def test_set_list_stores_accounts(self):
        accounts = [{'identifier': 'a@163.com', 'password': 'p'}]
        with mock.patch.object(console, '_prompt_accounts', return_value=(accounts, 'src')):
            self.assertTrue(run(io.StringIO(), console._set_list))
        self.assertEqual(console._CONFIG['accounts'], accounts)
        self.assertEqual(console._CONFIG['source'], 'src')

    def test_require_list_prompts_when_empty(self):
        with mock.patch.object(console, '_prompt_accounts', return_value=([{'identifier': 'a'}], 'src')):
            self.assertTrue(run(io.StringIO(), console._require_list))
        self.assertEqual(console._CONFIG['source'], 'src')

    def test_require_list_false_when_cancelled(self):
        with mock.patch.object(console, '_prompt_accounts', return_value=None):
            self.assertFalse(run(io.StringIO(), console._require_list))


class InteractiveLoopTest(_StateMixin):
    def test_set_list_then_run_cookies(self):
        runner = FakeRunner()
        accounts = [{'identifier': 'a@163.com', 'password': 'p'}]
        with mock.patch.object(console, 'is_interactive', return_value=True), \
                mock.patch.object(console, 'prompt', side_effect=['1', '3', '0']), \
                mock.patch.object(console, '_prompt_accounts', return_value=(accounts, 'src')), \
                mock.patch.object(console, 'confirm', return_value=True), \
                mock.patch.object(console, 'BatchCookieRunner', return_value=runner):
            code = run(io.StringIO(), console.run_interactive)
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0]['accounts'], accounts)

    def test_task_without_list_asks_for_list(self):
        runner = FakeRunner()
        accounts = [{'identifier': 'a@163.com', 'password': 'p'}]
        with mock.patch.object(console, 'is_interactive', return_value=True), \
                mock.patch.object(console, 'prompt', side_effect=['3', '0']), \
                mock.patch.object(console, '_prompt_accounts', return_value=(accounts, 'src')), \
                mock.patch.object(console, 'confirm', return_value=True), \
                mock.patch.object(console, 'BatchCookieRunner', return_value=runner):
            code = run(io.StringIO(), console.run_interactive)
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.calls), 1)

    def test_realname_submit_uses_config(self):
        runner = FakeRunner('realname', summary={'total': 1, 'verified': 0, 'required': 1,
                                                 'unknown': 0, 'submitted': 1, 'submit_failed': 0,
                                                 'skipped': 0, 'needs_manual_verify': 0, 'failed': 0})
        accounts = [{'identifier': 'a@163.com', 'password': 'p', 'realname': '张三',
                     'id_num': '110101199001011237'}]
        with mock.patch.object(console, 'is_interactive', return_value=True), \
                mock.patch.object(console, 'prompt', side_effect=['1', '5', '0']), \
                mock.patch.object(console, '_prompt_accounts', return_value=(accounts, 'src')), \
                mock.patch.object(console, 'confirm', return_value=True), \
                mock.patch.object(console, 'BatchRealnameRunner', return_value=runner):
            code = run(io.StringIO(), console.run_interactive)
        self.assertEqual(code, 0)
        self.assertTrue(runner.calls[0]['submit'])


if __name__ == '__main__':
    unittest.main()
