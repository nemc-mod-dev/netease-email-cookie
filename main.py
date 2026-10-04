#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网易账号批量工具 —— 纯控制台入口。

定位：喂进一批账号，批量转 Cookie，或批量做实名审查/提交。
没有"主账号"、没有跨运行的会话；每个账号在自己的处理步骤里独立登录。

用法::

    python main.py                    # 交互式菜单
    python main.py cookies   --input accounts.txt
    python main.py realname  --input accounts.txt [--submit]
    python main.py result

账号来源（``--input``，或交互时选择）：

- 文件路径；``-`` 表示从标准输入读取
- 文本格式：``邮箱----密码``，实名可写 ``邮箱----密码----姓名----证件号``
- JSON：数组或 ``{"accounts": [...]}``
"""

import argparse
import json
import os
import sys

from console_ui import (
    badge,
    banner,
    blank,
    confirm,
    echo,
    fields,
    is_interactive,
    legend,
    menu,
    progress_line,
    prompt,
    read_multiline,
    section,
    style,
    table,
)
from services.account_input import load_accounts, parse_accounts_text
from services.batch_service import BatchCookieRunner, BatchRealnameRunner
from services.realname_service import (
    REALNAME_REQUIRED,
    REALNAME_UNKNOWN,
    REALNAME_VERIFIED,
)

BATCH_OUTPUT_ROOT = 'artifacts/batch'
PREVIEW_LIMIT = 15

# 进程内记住上次用的清单与来源，省得每轮重贴。
_LAST_ACCOUNTS = {'items': None, 'source': ''}

# 阶段/状态 → (中文文案, 颜色语义)
COOKIE_STAGES = {
    'cookie_ready': ('已生成 Cookie', 'success'),
    'needs_manual_verify': ('需人工验证', 'warn'),
    'device_failed': ('设备初始化失败', 'error'),
    'login_failed': ('登录失败', 'error'),
    'missing_password': ('缺少密码', 'error'),
    'need_sms_code': ('缺少短信验证码', 'error'),
    'export_failed': ('导出失败', 'error'),
    'error': ('异常', 'error'),
}

REALNAME_STATES = {
    REALNAME_VERIFIED: ('已实名', 'success'),
    REALNAME_REQUIRED: ('需要实名', 'warn'),
    REALNAME_UNKNOWN: ('状态未知', 'muted'),
}


# --------------------------------------------------------------------------
# 账号来源
# --------------------------------------------------------------------------

def _prompt_accounts():
    """返回 (accounts, source_label)；取消返回 None。"""
    menu([('1', '从文件读取', 'accounts.txt / accounts.json'), ('2', '控制台粘贴', '每行一条')],
         title='账号来源')
    blank()
    choice = prompt('请选择', default='1')

    if choice.startswith('2'):
        echo()
        echo('  ' + style('每行一条：', 'dim') + '邮箱----密码')
        echo('  ' + style('实名提交可再补两段：', 'dim') + '邮箱----密码----姓名----证件号')
        echo('  ' + style('输入空行结束。', 'dim'))
        blank()
        try:
            accounts = parse_accounts_text(read_multiline())
        except ValueError as e:
            echo()
            echo('  ' + badge(f'解析失败: {e}', 'error'))
            return None
        if not accounts:
            echo()
            echo('  ' + badge('没有读到任何账号。', 'warn'))
            return None
        return accounts, '控制台粘贴'

    echo()
    path = prompt('文件路径', default='accounts.txt')
    try:
        return load_accounts(path), path
    except FileNotFoundError:
        echo()
        echo('  ' + badge(f'文件不存在: {path}', 'error'))
    except (ValueError, OSError) as e:
        echo()
        echo('  ' + badge(f'读取失败: {e}', 'error'))
    return None


def _resolve_accounts(args):
    path = getattr(args, 'input', None)
    if path:
        try:
            return load_accounts(path), path
        except FileNotFoundError:
            echo(style(f'文件不存在: {path}', 'bright_red'))
        except (ValueError, OSError) as e:
            echo(style(f'读取失败: {e}', 'bright_red'))
        return None
    if _LAST_ACCOUNTS['items']:
        reuse = confirm(f"沿用上次清单（{_LAST_ACCOUNTS['source']}，"
                        f"{len(_LAST_ACCOUNTS['items'])} 个账号）？", default=True)
        if reuse:
            return list(_LAST_ACCOUNTS['items']), _LAST_ACCOUNTS['source']
    if is_interactive():
        resolved = _prompt_accounts()
        if resolved:
            _LAST_ACCOUNTS['items'] = list(resolved[0])
            _LAST_ACCOUNTS['source'] = resolved[1]
        return resolved
    echo(style('缺少 --input（文件路径，或 - 表示从标准输入读取）。', 'bright_red'))
    return None


def _ask_delay(args, count):
    delay = getattr(args, 'delay', None)
    if delay is None:
        if count <= 1:
            return 0.0
        delay = prompt('请求间隔(秒)', default='2')
    try:
        return max(0.0, float(delay))
    except (TypeError, ValueError):
        return 2.0


# --------------------------------------------------------------------------
# 清单预览 / 进度 / 汇总
# --------------------------------------------------------------------------

def _account_rows(accounts):
    rows = []
    for i, account in enumerate(accounts, 1):
        ident = account.get('identifier') or account.get('label') or '—'
        if account.get('sauth') or account.get('sauth_file'):
            mode = '已有会话'
        elif account.get('mode') == 'phone':
            mode = '手机号'
        else:
            mode = '邮箱'
        has_identity = '有' if (account.get('realname') and account.get('id_num')) else '—'
        rows.append([i, ident, mode, has_identity])
    return rows


def _print_accounts(accounts, source):
    blank()
    section('待处理清单')
    table(['#', '账号', '登录方式', '身份信息'], _account_rows(accounts),
          aligns=['right', 'left', 'left', 'center'], max_rows=PREVIEW_LIMIT)
    blank()
    echo('  ' + style(f'来源 {source} · 共 {len(accounts)} 个账号', 'dim'))


def _cookie_progress(index, total, record):
    stage = record.get('stage')
    text, kind = COOKIE_STAGES.get(stage, (stage or '处理中', 'info'))
    if stage == 'needs_manual_verify':
        note = f"ticket={record.get('ticket')}"
    elif record.get('error'):
        note = record['error']
    else:
        note = ''
    progress_line(index, total, record.get('identifier') or record.get('label') or '—',
                  text, kind, note)


def _realname_progress(index, total, record):
    stage = record.get('stage')
    if stage == 'needs_manual_verify':
        text, kind = '需人工验证', 'warn'
    elif record.get('submit_status') == 'success':
        text, kind = '已提交实名', 'success'
    elif record.get('submit_status') == 'skipped':
        text, kind = '跳过（缺身份）', 'muted'
    elif stage == 'submit_failed':
        text, kind = '提交失败', 'error'
    elif stage in ('review_failed', 'error'):
        text, kind = '审查失败', 'error'
    else:
        text, kind = REALNAME_STATES.get(record.get('realname_state'), ('未知', 'muted'))

    if stage == 'needs_manual_verify':
        note = f"ticket={record.get('ticket')}"
    elif record.get('error'):
        note = record['error']
    else:
        note = ''
    progress_line(index, total, record.get('identifier') or record.get('label') or '—',
                  text, kind, note)


def _print_manual(report):
    manual = report.get('needs_manual_verify') or []
    if not manual:
        return
    blank()
    section('需要人工完成安全验证')
    echo('  ' + style('以下账号本次已跳过，处理完验证后重新跑一遍即可。', 'dim'))
    blank()
    rows = [[m.get('index', ''), m.get('identifier', ''), m.get('ticket') or '—',
             m.get('verify_url') or '—'] for m in manual]
    table(['#', '账号', 'ticket', '验证链接'], rows, aligns=['right', 'left', 'left', 'left'])
    if report.get('needs_verify_json'):
        blank()
        echo('  ' + style('已写入 ', 'dim') + report['needs_verify_json'])


def _summary_pairs(report):
    summary = report.get('summary', {})
    if report.get('kind') == 'cookie':
        return [
            ('总计', summary.get('total', 0)),
            ('成功', style(str(summary.get('ready', 0)), 'bright_green')),
            ('待人工验证', style(str(summary.get('needs_manual_verify', 0)), 'bright_yellow')),
            ('失败', style(str(summary.get('failed', 0)), 'bright_red')),
        ]
    pairs = [
        ('总计', summary.get('total', 0)),
        ('已实名', style(str(summary.get('verified', 0)), 'bright_green')),
        ('需要实名', style(str(summary.get('required', 0)), 'bright_yellow')),
        ('状态未知', style(str(summary.get('unknown', 0)), 'bright_black')),
    ]
    if report.get('submit_enabled'):
        pairs += [
            ('提交成功', style(str(summary.get('submitted', 0)), 'bright_green')),
            ('提交失败', style(str(summary.get('submit_failed', 0)), 'bright_red')),
            ('跳过', style(str(summary.get('skipped', 0)), 'bright_black')),
        ]
    pairs += [
        ('待人工验证', style(str(summary.get('needs_manual_verify', 0)), 'bright_yellow')),
        ('失败', style(str(summary.get('failed', 0)), 'bright_red')),
    ]
    return pairs


def _print_summary(report):
    blank()
    section('汇总')
    fields(_summary_pairs(report))
    _print_manual(report)
    if report.get('report_json'):
        blank()
        echo('  ' + style('报告  ', 'dim') + report['report_json'])
        echo('  ' + style('      ', 'dim') + str(report.get('report_csv')))


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_cookies(args, runner=None):
    resolved = _resolve_accounts(args)
    if not resolved:
        return 2
    accounts, source = resolved
    _print_accounts(accounts, source)
    delay = _ask_delay(args, len(accounts))

    if is_interactive():
        blank()
        if not confirm(f'对 {len(accounts)} 个账号执行「转 Cookie」？'):
            blank()
            echo('  ' + badge('已取消，未执行。', 'warn'))
            return 1

    runner = runner or BatchCookieRunner(output_root=getattr(args, 'output', None) or BATCH_OUTPUT_ROOT)
    blank()
    section('执行中')
    report = runner.run(accounts, delay=delay, on_progress=_cookie_progress)
    _print_summary(report)
    return 0


def cmd_realname(args, runner=None):
    resolved = _resolve_accounts(args)
    if not resolved:
        return 2
    accounts, source = resolved
    _print_accounts(accounts, source)

    submit = getattr(args, 'submit', None)
    if submit is None:
        blank()
        menu([('1', '只审查', '查看每个账号是否需要实名'),
              ('2', '审查后提交', '需要实名且有身份时才提交')], title='模式')
        blank()
        submit = prompt('请选择', default='1').startswith('2')
    delay = _ask_delay(args, len(accounts))

    if submit:
        blank()
        echo('  ' + badge('批量提交只使用各账号条目自带的真实身份；缺身份的账号会跳过。', 'warn'))
        if is_interactive() and not confirm('确认对「需要实名」的账号提交实名？', default=False):
            blank()
            echo('  ' + badge('已取消，未执行。', 'warn'))
            return 1
    elif is_interactive():
        blank()
        if not confirm(f'对 {len(accounts)} 个账号执行「实名审查」？'):
            blank()
            echo('  ' + badge('已取消，未执行。', 'warn'))
            return 1

    runner = runner or BatchRealnameRunner(output_root=getattr(args, 'output', None) or BATCH_OUTPUT_ROOT)
    blank()
    section('执行中')
    report = runner.run(accounts, submit=bool(submit), delay=delay, on_progress=_realname_progress)
    _print_summary(report)
    return 0


def _results_rows(report):
    rows = []
    kind = report.get('kind')
    for r in report.get('results', []):
        if kind == 'cookie':
            text, _ = COOKIE_STAGES.get(r.get('stage'), (r.get('stage') or '', 'info'))
            rows.append([r.get('index', ''), r.get('identifier') or r.get('label') or '—',
                         text, os.path.basename(r.get('nemc_path') or '') or '—'])
        else:
            if r.get('submit_status') == 'success':
                text = '已提交实名'
            elif r.get('submit_status') == 'skipped':
                text = '跳过（缺身份）'
            elif r.get('stage') == 'needs_manual_verify':
                text = '需人工验证'
            elif r.get('stage') in ('review_failed', 'error', 'submit_failed'):
                text = '失败'
            else:
                text, _ = REALNAME_STATES.get(r.get('realname_state'), ('未知', 'muted'))
            rows.append([r.get('index', ''), r.get('identifier') or r.get('label') or '—',
                         text, r.get('realname_masked') or '—'])
    return rows


def cmd_result(args):
    root = getattr(args, 'output', None) or BATCH_OUTPUT_ROOT
    if not os.path.isdir(root):
        echo(style('还没有任何批量运行记录。', 'bright_yellow'))
        return 1
    runs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    if not runs:
        echo(style('还没有任何批量运行记录。', 'bright_yellow'))
        return 1
    run_id = getattr(args, 'run_id', None) or runs[-1]
    report_path = os.path.join(root, run_id, 'report.json')
    if not os.path.exists(report_path):
        echo(style(f'找不到报告: {report_path}', 'bright_red'))
        return 1
    with open(report_path, encoding='utf-8') as f:
        report = json.load(f)

    blank()
    section(f'运行 {run_id}')
    fields([('类型', '转 Cookie' if report.get('kind') == 'cookie' else '实名'),
            ('时间', report.get('generated_at', '—'))])
    _print_summary(report)

    rows = _results_rows(report)
    if rows:
        blank()
        section('逐账号结果')
        if report.get('kind') == 'cookie':
            table(['#', '账号', '状态', 'Cookie 文件'], rows,
                  aligns=['right', 'left', 'left', 'left'])
        else:
            table(['#', '账号', '状态', '身份(脱敏)'], rows,
                  aligns=['right', 'left', 'left', 'left'])
    return 0


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog='main.py',
        description='网易账号批量工具（转 Cookie / 实名，纯控制台）',
        epilog='不带子命令时进入交互式菜单。',
    )
    sub = parser.add_subparsers(dest='command', metavar='<命令>')

    sp = sub.add_parser('cookies', help='批量转 Cookie')
    sp.add_argument('--input', help='账号文件，- 表示从 stdin 读取')
    sp.add_argument('--delay', type=float, default=2.0, help='账号间隔秒数，默认 2')
    sp.add_argument('--output', default=BATCH_OUTPUT_ROOT, help='报告输出根目录')

    sp = sub.add_parser('realname', help='批量实名（默认只审查）')
    sp.add_argument('--input', help='账号文件，- 表示从 stdin 读取')
    sp.add_argument('--submit', action='store_true', help='对需要实名的账号提交（默认只审查）')
    sp.add_argument('--delay', type=float, default=2.0, help='账号间隔秒数，默认 2')
    sp.add_argument('--output', default=BATCH_OUTPUT_ROOT, help='报告输出根目录')

    sp = sub.add_parser('result', help='查看最近的批量结果')
    sp.add_argument('--run-id', help='指定运行目录名，默认最近一次')
    sp.add_argument('--output', default=BATCH_OUTPUT_ROOT, help='报告输出根目录')

    return parser


# --------------------------------------------------------------------------
# 交互式菜单
# --------------------------------------------------------------------------

MENU = [
    ('1', '批量转 Cookie', '登录并生成可复用 Cookie'),
    ('2', '批量实名', '先审查，按需提交'),
    ('3', '查看上次结果', '显示最近一次运行的报告'),
    ('0', '退出', ''),
]


def run_interactive(_app=None):
    if not is_interactive():
        echo('当前非交互环境。请使用子命令，例如:')
        echo('  python main.py realname --input accounts.txt')
        echo('查看用法: python main.py --help')
        return 2

    banner('网易账号批量工具', '批量转 Cookie · 批量实名审查/提交')
    blank()
    legend()

    while True:
        blank()
        menu(MENU, title='主菜单')
        blank()
        choice = prompt('请选择')
        if choice in ('0', 'q', 'quit', 'exit'):
            blank()
            echo('  再见。')
            return 0
        if choice == '1':
            cmd_cookies(argparse.Namespace(input=None, delay=None, output=BATCH_OUTPUT_ROOT))
        elif choice == '2':
            cmd_realname(argparse.Namespace(input=None, submit=None, delay=None, output=BATCH_OUTPUT_ROOT))
        elif choice == '3':
            cmd_result(argparse.Namespace(run_id=None, output=BATCH_OUTPUT_ROOT))
        else:
            blank()
            echo('  ' + badge('无效选择，请重新输入。', 'warn'))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        try:
            return run_interactive()
        except KeyboardInterrupt:
            blank()
            echo('  已中断。')
            return 130

    handlers = {'cookies': cmd_cookies, 'realname': cmd_realname, 'result': cmd_result}
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args) or 0
    except KeyboardInterrupt:
        blank()
        echo('  已中断。')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
