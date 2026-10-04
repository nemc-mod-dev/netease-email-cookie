#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""账号输入解析测试。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.account_input import load_accounts, parse_accounts_text


class ParseLineFormatTest(unittest.TestCase):
    def test_email_password(self):
        accounts = parse_accounts_text('a@163.com----pw123\nb@163.com----pw456')
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]['identifier'], 'a@163.com')
        self.assertEqual(accounts[0]['password'], 'pw123')
        self.assertEqual(accounts[0]['mode'], 'email')
        self.assertEqual(accounts[0]['label'], 'a@163.com')

    def test_email_password_identity(self):
        accounts = parse_accounts_text('a@163.com----pw----张三----110101199001011237')
        self.assertEqual(accounts[0]['realname'], '张三')
        self.assertEqual(accounts[0]['id_num'], '110101199001011237')

    def test_comments_and_blank_lines_ignored(self):
        text = '# 这是注释\n\n a@163.com----pw \n\n# 尾注释\n'
        accounts = parse_accounts_text(text)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['identifier'], 'a@163.com')

    def test_empty_text(self):
        self.assertEqual(parse_accounts_text('   \n  '), [])


class ParseJsonTest(unittest.TestCase):
    def test_json_array(self):
        text = json.dumps([{'identifier': 'a@163.com', 'password': 'pw'}])
        accounts = parse_accounts_text(text)
        self.assertEqual(accounts[0]['label'], 'a@163.com')

    def test_objects_wrapper(self):
        text = json.dumps({'accounts': [{'identifier': 'a@163.com', 'sauth': {'sdkuid': 'u'}}]})
        accounts = parse_accounts_text(text)
        self.assertEqual(accounts[0]['sauth']['sdkuid'], 'u')

    def test_json_lines(self):
        text = '{"identifier": "a@163.com", "password": "p"}\n{"identifier": "b@163.com", "password": "q"}'
        accounts = parse_accounts_text(text)
        self.assertEqual([a['identifier'] for a in accounts], ['a@163.com', 'b@163.com'])

    def test_string_items_in_json(self):
        text = json.dumps(['a@163.com----pw'])
        accounts = parse_accounts_text(text)
        self.assertEqual(accounts[0]['password'], 'pw')


class LoadAccountsTest(unittest.TestCase):
    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, 'accounts.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('a@163.com----pw\n')
            accounts = load_accounts(path)
            self.assertEqual(accounts[0]['identifier'], 'a@163.com')

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_accounts('/nonexistent/accounts.txt')


if __name__ == '__main__':
    unittest.main()
