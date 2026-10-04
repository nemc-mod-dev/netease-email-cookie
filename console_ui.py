#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台排版层。

只依赖标准库。提供：

- 颜色（自动检测 TTY / 尊重 ``NO_COLOR`` / ``FORCE_COLOR``）
- 中英混排对齐（按东亚字符宽度计算，ANSI 序列不计宽）
- 分区标题、分隔线、图例、键值块、表格、菜单、进度行
- 交互原语（``prompt`` / ``confirm`` / ``read_multiline``）

排版约定：所有"块"自带换行与缩进；调用方只管顺序，不关心空格。
"""

import getpass
import os
import re
import shutil
import sys
import unicodedata

MAX_WIDTH = 68

# 制表符(─│╭…)属 East Asian Ambiguous：多数终端按 1 宽，CJK 终端可能按 2 宽。
# 若框线/分隔线在你的终端里对不齐，设 CONSOLE_AMBIGUOUS_WIDE=1。
AMBIGUOUS_WIDE = os.environ.get('CONSOLE_AMBIGUOUS_WIDE') == '1'

# --------------------------------------------------------------------------
# 颜色
# --------------------------------------------------------------------------

_CODES = {
    'reset': '0',
    'bold': '1', 'dim': '2', 'italic': '3', 'underline': '4',
    'red': '31', 'green': '32', 'yellow': '33', 'blue': '34',
    'magenta': '35', 'cyan': '36', 'white': '37',
    'bright_black': '90', 'bright_red': '91', 'bright_green': '92',
    'bright_yellow': '93', 'bright_blue': '94', 'bright_magenta': '95',
    'bright_cyan': '96', 'bright_white': '97',
}

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# 状态语义 → (颜色, 符号)。改主题只改这一处。
STATUS_STYLES = {
    'success': ('bright_green', '✔'),
    'warn': ('bright_yellow', '!'),
    'error': ('bright_red', '×'),
    'info': ('bright_cyan', '·'),
    'muted': ('bright_black', '·'),
}

LEGEND = [
    ('success', '成功'),
    ('warn', '需处理'),
    ('error', '失败'),
    ('info', '进行中/信息'),
    ('muted', '跳过/忽略'),
]


def _detect_color():
    if os.environ.get('NO_COLOR'):
        return False
    if os.environ.get('FORCE_COLOR'):
        return True
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


_COLOR = _detect_color()


def set_color(enabled):
    """强制开关颜色（测试用）。"""
    global _COLOR
    _COLOR = bool(enabled)


def color_enabled():
    return _COLOR


def style(text, *names):
    if not _COLOR or not names:
        return str(text)
    codes = [_CODES[n] for n in names if n in _CODES]
    if len(codes) == 1 and codes[0] == '0':
        return f'\033[0m{text}'
    if not codes:
        return str(text)
    return '\033[' + ';'.join(codes) + 'm' + str(text) + '\033[0m'


def strip_ansi(text):
    return _ANSI_RE.sub('', str(text))


# --------------------------------------------------------------------------
# 宽度与对齐
# --------------------------------------------------------------------------

def display_width(text):
    return sum(_char_width(ch) for ch in strip_ansi(text))


def _char_width(ch):
    if unicodedata.combining(ch):
        return 0
    east_asian = unicodedata.east_asian_width(ch)
    if east_asian in ('W', 'F'):
        return 2
    if east_asian == 'A' and AMBIGUOUS_WIDE:
        return 2
    return 1


def truncate(text, width):
    text = str(text)
    if display_width(text) <= width:
        return text
    out, used = '', 0
    for ch in text:
        cw = _char_width(ch)
        if used + cw > width - 1:
            break
        out += ch
        used += cw
    return out + '…'


def pad(text, width, align='left'):
    text = str(text)
    gap = width - display_width(text)
    if gap <= 0:
        return text
    if align == 'right':
        return ' ' * gap + text
    if align == 'center':
        left = gap // 2
        return ' ' * left + text + ' ' * (gap - left)
    return text + ' ' * gap


def term_width():
    try:
        return max(40, min(shutil.get_terminal_size((MAX_WIDTH, 24)).columns, 100))
    except Exception:
        return MAX_WIDTH


def content_width():
    return min(term_width(), MAX_WIDTH)


# --------------------------------------------------------------------------
# 输出块
# --------------------------------------------------------------------------

def echo(text=''):
    print(text)


def blank(n=1):
    for _ in range(max(0, n)):
        print()


def divider(width=None, char='─'):
    echo(style(char * (width or content_width()), 'bright_black'))


def section(title, symbol='▍'):
    """分区标题 + 右延分隔线。"""
    label = f'{symbol} {title}'
    rule = '─' * max(0, content_width() - display_width(label) - 1)
    echo(style(label, 'bold', 'bright_blue') + ' ' + style(rule, 'bright_black'))


def banner(title, subtitle=None):
    width = content_width()
    inner = width - 2
    bar = style('│', 'bright_black')
    echo(style('╭' + '─' * inner + '╮', 'bright_black'))
    echo(bar + pad(' ' + style(title, 'bold', 'bright_cyan'), inner) + bar)
    if subtitle:
        echo(bar + pad(' ' + style(subtitle, 'dim'), inner) + bar)
    echo(style('╰' + '─' * inner + '╯', 'bright_black'))


def badge(text, kind='info'):
    color, symbol = STATUS_STYLES.get(kind, STATUS_STYLES['info'])
    return style(f'{symbol} {text}', color)


def legend(title='图例'):
    parts = [badge(name, kind) for kind, name in LEGEND]
    echo('  ' + style(title + '  ', 'dim') + '   '.join(parts))


def fields(pairs, indent=2, key_width=None, key_style='dim'):
    pairs = [(str(k), v) for k, v in pairs]
    width = key_width or (max(display_width(k) for k, _ in pairs) if pairs else 0)
    for key, value in pairs:
        echo(' ' * indent + style(pad(key, width), key_style) + '  ' + str(value))


def table(headers, rows, aligns=None, indent=2, max_rows=None):
    rows = list(rows)
    aligns = aligns or ['left'] * len(headers)
    widths = [display_width(str(h)) for h in headers]
    shown = rows[:max_rows] if max_rows else rows
    for row in shown:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(str(cell)))

    def line(cells, cell_style=None):
        out = []
        for i, cell in enumerate(cells):
            cell = pad(str(cell), widths[i], aligns[i])
            out.append(style(cell, cell_style) if cell_style else cell)
        return ' ' * indent + '  '.join(out).rstrip()

    echo(line([style(str(h), 'bold') for h in headers]))
    echo(' ' * indent + style('  '.join('─' * w for w in widths), 'bright_black'))
    for row in shown:
        echo(line(row))
    if max_rows and len(rows) > max_rows:
        echo(' ' * indent + style(f'… 另有 {len(rows) - max_rows} 个账号', 'dim'))


def menu(items, title=None):
    """items: [(key, label[, hint])]"""
    if title:
        section(title)
    norm = [(str(i[0]), str(i[1]), str(i[2]) if len(i) > 2 else '') for i in items]
    label_width = max((display_width(label) for _, label, _ in norm), default=0)
    for key, label, hint in norm:
        key_cell = style(pad(key, 2, align='right'), 'bold', 'bright_cyan')
        line = '   ' + key_cell + '  ' + pad(label, label_width)
        if hint:
            line += '  ' + style(hint, 'dim')
        echo(line.rstrip())


def progress_line(index, total, label, text, kind='info', note=''):
    width = len(str(total))
    counter = style(f'[{index:>{width}}/{total}]', 'bright_black')
    name = pad(truncate(label, 30), 30)
    line = f'  {counter}  {name}  {badge(text, kind)}'
    if note:
        line += '  ' + style(note, 'dim')
    echo(line.rstrip())


# --------------------------------------------------------------------------
# 交互
# --------------------------------------------------------------------------

def is_interactive():
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _ask_raw(text):
    try:
        return input(text)
    except EOFError:
        echo()
        return None


def prompt(text, default=None):
    suffix = f' [{default}]' if default not in (None, '') else ''
    raw = _ask_raw(style('? ', 'bold', 'bright_cyan') + text + suffix + ': ')
    if raw is None:
        return default if default is not None else ''
    raw = raw.strip()
    if not raw:
        return default if default is not None else ''
    return raw


def prompt_secret(text):
    try:
        return getpass.getpass(style('? ', 'bold', 'bright_cyan') + text + ': ')
    except EOFError:
        echo()
        return ''


_YES = {'y', 'yes', '1', '是', '确认', 'ok', 'o'}
_NO = {'n', 'no', '0', '否', '取消', 'q'}


def confirm(text, default=True):
    hint = 'Y/n' if default else 'y/N'
    raw = prompt(f'{text} ({hint})', default='')
    raw = (raw or '').strip().lower()
    if not raw:
        return default
    if raw in _YES:
        return True
    if raw in _NO:
        return False
    return default


def read_multiline(sentinel=''):
    """逐行读取直到空行；带行首竖线引导，方便粘贴。"""
    lines = []
    while True:
        raw = _ask_raw(style('  │ ', 'bright_black'))
        if raw is None:
            break
        if raw.strip() == sentinel:
            break
        lines.append(raw)
    return '\n'.join(lines)
