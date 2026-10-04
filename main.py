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

from console_ui import confirm, echo, is_interactive, prompt, read_multiline
from services.account_input import load_accounts, parse_accounts_text
from services.batch_service import BatchCookieRunner, BatchRealnameRunner
from services.realname_service import (
    REALNAME_REQUIRED,
    REALNAME_UNKNOWN,
    REALNAME_VERIFIED,
)

BATCH_OUTPUT_ROOT = 'artifacts/batch'

STATE_LABEL = {
    REALNAME_VERIFIED: '已实名',
    REALNAME_REQUIRED: '需要实名',
    REALNAME_UNKNOWN: '状态未知',
}


# --------------------------------------------------------------------------
# 账号来源
# --------------------------------------------------------------------------

def _prompt_accounts():
    echo('账号来源: 1) 文件  2) 控制台粘贴')
    source = prompt('选择', default='1')
    if source.startswith('2'):
        echo('每行一条：邮箱----密码（实名提交可写 邮箱----密码----姓名----证件号）')
        echo('粘贴完成后输入空行结束：')
        try:
            accounts = parse_accounts_text(read_multiline())
        except ValueError as e:
            echo(f'解析失败: {e}')
            return None
        if not accounts:
            echo('没有读到任何账号。')
            return None
        return accounts

    path = prompt('文件路径', default='accounts.json')
    try:
        return load_accounts(path)
    except FileNotFoundError:
        echo(f'文件不存在: {path}')
    except (ValueError, OSError) as e:
        echo(f'读取失败: {e}')
    return None


def _resolve_accounts(args):
    path = getattr(args, 'input', None)
    if path:
        try:
            return load_accounts(path)
        except FileNotFoundError:
            echo(f'文件不存在: {path}')
        except (ValueError, OSError) as e:
            echo(f'读取失败: {e}')
        return None
    if is_interactive():
        return _prompt_accounts()
    echo('缺少 --input（文件路径，或 - 表示从标准输入读取）。')
    return None


def _ask_delay(args):
    delay = getattr(args, 'delay', None)
    if delay is None:
        delay = prompt('请求间隔(秒)', default='2')
    try:
        return max(0.0, float(delay))
    except (TypeError, ValueError):
        return 2.0


# --------------------------------------------------------------------------
# 进度与汇总输出
# --------------------------------------------------------------------------

def _cookie_progress(index, total, record):
    line = f"[{index}/{total}] {record.get('identifier') or record.get('label')} -> {record.get('stage')}"
    if record.get('nemc_path'):
        line += f"  {record['nemc_path']}"
    if record.get('stage') == 'needs_manual_verify':
        line += f"  需人工验证 ticket={record.get('ticket')}"
    if record.get('error'):
        line += f"  error={record['error']}"
    echo(line)


def _realname_progress(index, total, record):
    state = STATE_LABEL.get(record.get('realname_state'), record.get('realname_state'))
    line = f"[{index}/{total}] {record.get('identifier') or record.get('label')} -> {state} ({record.get('stage')})"
    if record.get('submit_status'):
        line += f" submit={record['submit_status']}"
    if record.get('stage') == 'needs_manual_verify':
        line += f"  需人工验证 ticket={record.get('ticket')}"
    if record.get('error'):
        line += f"  error={record['error']}"
    echo(line)


def _print_manual(report):
    manual = report.get('needs_manual_verify') or []
    if not manual:
        return
    echo()
    echo('以下账号需要人工完成安全验证，本次已跳过：')
    for item in manual:
        echo(f"  - {item.get('identifier')}  ticket={item.get('ticket')}")
        if item.get('verify_url'):
            echo(f"    {item['verify_url']}")
    if report.get('needs_verify_json'):
        echo(f"已写入: {report['needs_verify_json']}")


def _print_summary(report):
    summary = report.get('summary', {})
    echo()
    echo('=== 汇总 ===')
    if report.get('kind') == 'cookie':
        echo(f"总计 {summary.get('total')} | 成功 {summary.get('ready')} | "
             f"待人工验证 {summary.get('needs_manual_verify')} | 失败 {summary.get('failed')}")
    else:
        echo(f"总计 {summary.get('total')} | 已实名 {summary.get('verified')} | "
             f"需要实名 {summary.get('required')} | 未知 {summary.get('unknown')}")
        if report.get('submit_enabled'):
            echo(f"提交成功 {summary.get('submitted')} | 提交失败 {summary.get('submit_failed')} | "
                 f"跳过 {summary.get('skipped')}")
        echo(f"待人工验证 {summary.get('needs_manual_verify')} | 失败 {summary.get('failed')}")
    _print_manual(report)
    if report.get('report_json'):
        echo(f"报告: {report['report_json']}")
        echo(f"      {report.get('report_csv')}")


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_cookies(args, runner=None):
    accounts = _resolve_accounts(args)
    if not accounts:
        return 2
    echo(f'读取到 {len(accounts)} 个账号。')
    delay = _ask_delay(args)
    if is_interactive() and not confirm(f'将对 {len(accounts)} 个账号执行「转 Cookie」（间隔 {delay:g}s）？'):
        echo('已取消。')
        return 1
    runner = runner or BatchCookieRunner(output_root=getattr(args, 'output', None) or BATCH_OUTPUT_ROOT)
    report = runner.run(accounts, delay=delay, on_progress=_cookie_progress)
    _print_summary(report)
    return 0


def cmd_realname(args, runner=None):
    accounts = _resolve_accounts(args)
    if not accounts:
        return 2
    echo(f'读取到 {len(accounts)} 个账号。')

    submit = getattr(args, 'submit', None)
    if submit is None:
        submit = prompt('模式: 1) 只审查  2) 审查后提交', default='1').startswith('2')
    delay = _ask_delay(args)

    if submit:
        echo('提示：批量提交只使用每个账号条目自带的真实身份；未提供身份的账号会自动跳过。')
        if is_interactive() and not confirm('确认对「需要实名」的账号提交实名？'):
            echo('已取消。')
            return 1
    elif is_interactive() and not confirm(f'将对 {len(accounts)} 个账号执行「实名审查」？'):
        echo('已取消。')
        return 1

    runner = runner or BatchRealnameRunner(output_root=getattr(args, 'output', None) or BATCH_OUTPUT_ROOT)
    report = runner.run(accounts, submit=bool(submit), delay=delay, on_progress=_realname_progress)
    _print_summary(report)
    return 0


def cmd_result(args):
    root = getattr(args, 'output', None) or BATCH_OUTPUT_ROOT
    if not os.path.isdir(root):
        echo('还没有任何批量运行记录。')
        return 1
    runs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    if not runs:
        echo('还没有任何批量运行记录。')
        return 1
    run_id = getattr(args, 'run_id', None) or runs[-1]
    report_path = os.path.join(root, run_id, 'report.json')
    if not os.path.exists(report_path):
        echo(f'找不到报告: {report_path}')
        return 1
    with open(report_path, encoding='utf-8') as f:
        report = json.load(f)
    echo(f"运行: {run_id}  类型: {report.get('kind')}  时间: {report.get('generated_at')}")
    _print_summary(report)
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
    ('1', '批量转 Cookie'),
    ('2', '批量实名（默认只审查，可选提交）'),
    ('3', '查看上次结果'),
    ('0', '退出'),
]


def run_interactive(_app=None):
    if not is_interactive():
        echo('当前非交互环境。请使用子命令，例如:')
        echo('  python main.py realname --input accounts.txt')
        echo('查看用法: python main.py --help')
        return 2

    echo('网易账号批量工具')
    while True:
        echo()
        echo('=== 主菜单 ===')
        for key, label in MENU:
            echo(f'  {key}) {label}')
        try:
            choice = input('请选择: ').strip()
        except EOFError:
            echo()
            return 0
        if choice in ('0', 'q', 'quit', 'exit'):
            echo('再见。')
            return 0
        if choice == '1':
            cmd_cookies(argparse.Namespace(input=None, delay=None, output=BATCH_OUTPUT_ROOT))
        elif choice == '2':
            cmd_realname(argparse.Namespace(input=None, submit=None, delay=None, output=BATCH_OUTPUT_ROOT))
        elif choice == '3':
            cmd_result(argparse.Namespace(run_id=None, output=BATCH_OUTPUT_ROOT))
        else:
            echo('无效选择，请重新输入。')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        return run_interactive()

    handlers = {'cookies': cmd_cookies, 'realname': cmd_realname, 'result': cmd_result}
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args) or 0
    except KeyboardInterrupt:
        echo()
        echo('已中断。')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
