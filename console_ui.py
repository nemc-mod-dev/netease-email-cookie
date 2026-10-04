#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯控制台的输入/输出原语，不依赖任何第三方库。"""

import getpass
import sys


def echo(message=''):
    print(message)


def _secret_input(prompt_text):
    try:
        return getpass.getpass(prompt_text)
    except Exception:
        # getpass 在非 TTY / 无控制终端时会失败，回退到普通输入
        return input(prompt_text)


def prompt(label, default='', required=False):
    suffix = f' [{default}]' if default else ''
    while True:
        value = input(f'{label}{suffix}: ').strip()
        if not value and default:
            value = default
        if value or not required:
            return value
        echo('该项不能为空，请重新输入。')


def prompt_secret(label, required=False):
    while True:
        value = _secret_input(f'{label}: ').strip()
        if value or not required:
            return value
        echo('该项不能为空，请重新输入。')


def confirm(label, default=False):
    options = 'Y/n' if default else 'y/N'
    answer = input(f'{label} [{options}]: ').strip().lower()
    if not answer:
        return default
    return answer in ('y', 'yes', '是')


def read_multiline(until_blank=True):
    """读取多行输入，遇到空行结束（或 EOF）。"""
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if until_blank and not line.strip():
            break
        lines.append(line)
    return '\n'.join(lines)


def is_interactive():
    return sys.stdin is not None and sys.stdin.isatty()
