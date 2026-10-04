#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号输入解析：统一处理控制台粘贴、文本文件与 JSON。

支持的格式：

1. ``邮箱----密码``，每行一条
2. ``邮箱----密码----姓名----证件号``，每行一条（实名提交用）
3. JSON 数组，或 ``{"accounts": [...]}``（字段见 ``accounts.example.json``）
4. JSON Lines：每行一个 JSON 对象

``#`` 开头的行会被忽略。第 3/4 种写法可以额外带上 ``sauth`` / ``sauth_file`` /
``sms_code`` / ``mode`` 等字段。
"""

import json
import sys

DELIMITER = '----'


def _parse_line(line):
    parts = [part.strip() for part in line.split(DELIMITER)]
    entry = {
        'identifier': parts[0],
        'mode': 'email',
        'label': parts[0],
    }
    if len(parts) > 1 and parts[1]:
        entry['password'] = parts[1]
    if len(parts) > 2 and parts[2]:
        entry['realname'] = parts[2]
    if len(parts) > 3 and parts[3]:
        entry['id_num'] = parts[3]
    return entry


def _normalize_entry(entry):
    if isinstance(entry, str):
        return _parse_line(entry)
    if not isinstance(entry, dict):
        raise ValueError(f'无法识别的账号条目: {entry!r}')
    entry = dict(entry)
    entry.setdefault('mode', 'email')
    entry.setdefault('label', entry.get('identifier') or 'account')
    return entry


def _from_json(data):
    if isinstance(data, dict) and 'accounts' in data:
        data = data['accounts']
    if not isinstance(data, list):
        raise ValueError('JSON 账号应为数组，或 {"accounts": [...]}')
    return [_normalize_entry(item) for item in data]


def parse_accounts_text(text):
    """把一段文本解析成账号列表（dict）。无法解析时抛 ValueError。"""
    text = (text or '').strip()
    if not text:
        return []

    if text[0] in '[{':
        try:
            return _from_json(json.loads(text))
        except json.JSONDecodeError:
            pass

    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith('#')]
    if not lines:
        return []

    if all(ln.startswith('{') for ln in lines):
        return [_normalize_entry(json.loads(ln)) for ln in lines]

    return [_parse_line(ln) for ln in lines]


def load_accounts(path):
    """从文件（或 ``-`` 表示 stdin）读取账号。"""
    if path in (None, '', '-'):
        return parse_accounts_text(sys.stdin.read())
    with open(path, 'r', encoding='utf-8') as f:
        return parse_accounts_text(f.read())


__all__ = ['DELIMITER', 'parse_accounts_text', 'load_accounts']
