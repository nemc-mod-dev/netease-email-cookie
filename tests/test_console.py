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


class CookiesCommandTest(unittest.TestCase):
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


class RealnameCommandTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
