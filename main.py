#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网易邮箱 / Cookie 工具 —— 纯控制台入口。

用法::

    python main.py                 # 进入交互式菜单
    python main.py login --mode email --identifier you@163.com
    python main.py status
    python main.py realname-check
    python main.py batch-realname --input accounts.json

子命令一览见 ``python main.py --help``。
"""

import argparse
import shutil
import subprocess
import sys
import time

import batch_realname
from console_ui import (
    confirm,
    echo,
    format_status,
    is_interactive,
    print_result,
    prompt,
    prompt_secret,
)
from services.auth_service import NetEaseAuthService
from services.realname_service import (
    REALNAME_REQUIRED,
    REALNAME_UNKNOWN,
    REALNAME_VERIFIED,
    mask_id_num,
    mask_realname,
)
from services.verify_service import VERIFY_MANUAL_ONLY, VERIFY_RESOLVED
from workflow import AuthWorkflow

STATE_LABEL = {
    REALNAME_VERIFIED: '已实名',
    REALNAME_REQUIRED: '需要实名',
    REALNAME_UNKNOWN: '状态未知',
}


class ConsoleApp:
    """把服务层能力封装成控制台动作，便于子命令与交互菜单复用。"""

    def __init__(self, auth=None, workflow=None):
        self.auth = auth or NetEaseAuthService()
        self.workflow = workflow or AuthWorkflow(self.auth)
        self.pending_ticket = ''
        self.pending_phone = ''
        self.pending_verify_url = ''

    # ---- 会话 / 转换 ----
    def email_login(self, identifier, password):
        return self._remember(self.workflow.run_email_login(identifier, password))

    def request_phone_sms(self, identifier):
        self.pending_phone = identifier
        return self.workflow.request_phone_sms(identifier)

    def phone_login(self, identifier, sms_code):
        return self._remember(self.workflow.complete_phone_login(identifier, sms_code))

    def confirm_verification(self, ticket, label=None):
        label = label or self.pending_phone or self.auth.last_login_context.get('identifier') or 'verified_account'
        return self._remember(self.workflow.confirm_verification(ticket, label))

    def poll_verify(self, ticket, label=None, timeout=300, interval=5):
        """同步轮询验证状态，直到完成 / 需人工 / 超时。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.auth.check_verification_status(ticket)
            data = status.get('data') or {}
            if status.get('verify_state') == VERIFY_RESOLVED or (isinstance(data, dict) and data.get('user')):
                return self.confirm_verification(ticket, label)
            if status.get('status') in ('manual_required', 'error') or status.get('verify_state') == VERIFY_MANUAL_ONLY:
                return status
            time.sleep(interval)
        return {'status': 'timeout', 'message': f'等待安全验证超时（{timeout}s）'}

    # ---- 实名 ----
    def realname_check(self):
        return self.auth.check_realname_status()

    def realname_submit(self, realname, id_num, id_region='86'):
        return self.auth.submit_realname(realname, id_num, id_region=id_region)

    # ---- 其他 ----
    def mailbox(self):
        return self.workflow.fetch_mailbox()

    def export_restored(self, label='restored_session'):
        return self.auth.export_restored_session(label)

    def rebuild_device(self):
        return self.auth.rebuild_device()

    def status(self):
        return self.auth.get_state_snapshot()

    def open_verify_url(self, url):
        command = None
        for candidate in (['termux-open-url', url], ['xdg-open', url]):
            if shutil.which(candidate[0]):
                command = candidate
                break
        if command is None:
            return {'status': 'manual_required', 'message': '无法自动打开浏览器，请手动访问验证链接', 'verify_url': url}
        try:
            subprocess.Popen(command)
            return {'status': 'success', 'message': '已尝试在浏览器中打开验证链接', 'command': ' '.join(command)}
        except Exception as e:
            return {'status': 'manual_required', 'message': '打开验证链接失败，请手动访问', 'error': str(e), 'verify_url': url}

    def _remember(self, result):
        if result.get('ticket'):
            self.pending_ticket = result['ticket']
        if result.get('verify_url'):
            self.pending_verify_url = result['verify_url']
        return result


# --------------------------------------------------------------------------
# 子命令处理
# --------------------------------------------------------------------------

def _handle_verify(app, result, args):
    if result.get('status') != 'need_verify':
        return
    echo()
    echo('需要完成安全验证：')
    if result.get('verify_url'):
        echo(f"  验证链接: {result['verify_url']}")
    if result.get('ticket'):
        echo(f"  ticket  : {result['ticket']}")
    echo(f"  完成后可执行: python main.py verify --ticket {result.get('ticket', '')}")
    if getattr(args, 'open_url', False) and result.get('verify_url'):
        print_result(app.open_verify_url(result['verify_url']))
    if getattr(args, 'wait', False) and result.get('ticket'):
        echo('开始轮询等待验证完成（Ctrl-C 可中断）...')
        print_result(app.poll_verify(result['ticket'], args.label or app.pending_phone, timeout=args.timeout))


def cmd_login(app, args):
    identifier = args.identifier
    if not identifier:
        if not is_interactive():
            echo('缺少 --identifier。')
            return 2
        identifier = prompt('邮箱' if args.mode == 'email' else '手机号', required=True)

    if args.mode == 'phone':
        request = app.request_phone_sms(identifier)
        print_result(request, verbose=args.verbose)
        if request.get('status') != 'success':
            return 1
        sms_code = args.sms_code
        if not sms_code:
            if not is_interactive():
                echo('缺少 --sms-code。')
                return 2
            sms_code = prompt('短信验证码', required=True)
        result = app.phone_login(identifier, sms_code)
    else:
        password = args.password
        if not password:
            if not is_interactive():
                echo('缺少 --password。')
                return 2
            password = prompt_secret('密码', required=True)
        result = app.email_login(identifier, password)

    print_result(result, verbose=args.verbose)
    _handle_verify(app, result, args)
    if result.get('status') == 'success':
        return 0
    return 3 if result.get('status') == 'need_verify' else 1


def cmd_verify(app, args):
    result = app.confirm_verification(args.ticket, args.label)
    print_result(result, verbose=args.verbose)
    return 0 if result.get('status') == 'success' else 1


def cmd_send_sms(app, args):
    result = app.auth.send_verify_sms(args.ticket)
    print_result(result, verbose=args.verbose)
    return 0 if result.get('status') == 'success' else 1


def cmd_realname_check(app, args):
    result = app.realname_check()
    print_result(result, verbose=args.verbose)
    state = result.get('realname_state')
    echo(f"结论: {STATE_LABEL.get(state, state)}")
    return 0 if result.get('status') == 'success' else 1


def cmd_realname_submit(app, args):
    realname = args.realname
    id_num = args.id_num
    if not realname:
        if not is_interactive():
            echo('缺少 --realname。')
            return 2
        realname = prompt('实名姓名', required=True)
    if not id_num:
        if not is_interactive():
            echo('缺少 --id-num。')
            return 2
        id_num = prompt_secret('证件号', required=True)

    if not args.yes and is_interactive():
        if not confirm(f"确认提交实名（{mask_realname(realname)} / {mask_id_num(id_num)}）？"):
            echo('已取消。')
            return 1

    result = app.realname_submit(realname, id_num, args.id_region)
    print_result(result, verbose=args.verbose)
    return 0 if result.get('status') in ('success', 'partial') else 1


def cmd_mailbox(app, args):
    result = app.mailbox()
    print_result(result, verbose=args.verbose)
    return 0 if result.get('status') == 'success' else 1


def cmd_export(app, args):
    result = app.export_restored(args.label)
    print_result(result, verbose=args.verbose)
    return 0 if result.get('status') == 'success' else 1


def cmd_device(app, args):
    result = app.rebuild_device()
    print_result(result, verbose=args.verbose)
    return 0 if result.get('status') == 'success' else 1


def cmd_status(app, args):
    echo(format_status(app.status()))
    return 0


def cmd_batch_realname(app, args):
    extra = list(getattr(args, 'args', None) or [])
    if not extra:
        echo('用法: python main.py batch-realname --input accounts.json [--submit] [--delay 2]')
        return 2
    return batch_realname.main(extra)


COMMANDS = {
    'login': cmd_login,
    'verify': cmd_verify,
    'send-sms': cmd_send_sms,
    'realname-check': cmd_realname_check,
    'realname-submit': cmd_realname_submit,
    'mailbox': cmd_mailbox,
    'export': cmd_export,
    'device': cmd_device,
    'status': cmd_status,
    'batch-realname': cmd_batch_realname,
}


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('-v', '--verbose', action='store_true', help='打印完整原始结果')

    parser = argparse.ArgumentParser(
        prog='main.py',
        description='网易邮箱 / Cookie 工具（纯控制台）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='不带子命令时进入交互式菜单。',
    )
    sub = parser.add_subparsers(dest='command', metavar='<命令>')

    sp = sub.add_parser('login', parents=[common], help='邮箱/手机号转 Cookie')
    sp.add_argument('--mode', choices=['email', 'phone'], default='email')
    sp.add_argument('--identifier', help='邮箱或手机号')
    sp.add_argument('--password', help='邮箱密码（建议留空改为交互输入）')
    sp.add_argument('--sms-code', help='手机号模式的短信验证码')
    sp.add_argument('--label', default='', help='安全验证确认时使用的账号标签')
    sp.add_argument('--wait', action='store_true', help='触发安全验证时同步轮询等待')
    sp.add_argument('--open-url', action='store_true', help='触发安全验证时尝试打开验证链接')
    sp.add_argument('--timeout', type=int, default=300, help='--wait 的轮询超时秒数')

    sp = sub.add_parser('verify', parents=[common], help='提交安全验证 ticket')
    sp.add_argument('--ticket', required=True)
    sp.add_argument('--label', default='')

    sp = sub.add_parser('send-sms', parents=[common], help='为 ticket 发送安全验证短信')
    sp.add_argument('--ticket', required=True)

    sub.add_parser('realname-check', parents=[common], help='审查当前会话账号是否需要实名')

    sp = sub.add_parser('realname-submit', parents=[common], help='为当前会话账号提交实名')
    sp.add_argument('--realname')
    sp.add_argument('--id-num')
    sp.add_argument('--id-region', default='86')
    sp.add_argument('--yes', action='store_true', help='跳过二次确认')

    sub.add_parser('mailbox', parents=[common], help='获取邮箱消息列表')
    sp = sub.add_parser('export', parents=[common], help='重新导出已恢复的会话产物')
    sp.add_argument('--label', default='restored_session')
    sub.add_parser('device', parents=[common], help='重建本机设备信息')
    sub.add_parser('status', parents=[common], help='查看当前状态')

    sub.add_parser('batch-realname', help='批量实名认证（用 --input 指定账号文件，其余参数见 batch_realname.py）')

    return parser


# --------------------------------------------------------------------------
# 交互式菜单
# --------------------------------------------------------------------------

MENU = [
    ('1', '邮箱转 Cookie'),
    ('2', '手机号转 Cookie'),
    ('3', '继续安全验证（ticket）'),
    ('4', '审查实名状态'),
    ('5', '提交实名'),
    ('6', '获取邮件列表'),
    ('7', '导出已恢复会话'),
    ('8', '重建设备'),
    ('9', '查看状态'),
    ('10', '批量实名（说明）'),
    ('0', '退出'),
]


def _interactive_after_login(app, result):
    if result.get('status') != 'need_verify':
        return
    echo()
    echo(f"需要安全验证，验证链接: {result.get('verify_url')}")
    echo(f"ticket: {result.get('ticket')}")
    if result.get('verify_url') and confirm('是否打开验证链接？', default=False):
        print_result(app.open_verify_url(result['verify_url']))
    if result.get('ticket') and confirm('是否轮询等待验证完成？', default=True):
        print_result(app.poll_verify(result['ticket'], app.pending_phone or 'verified_account'))


def _interactive_dispatch(app, choice):
    if choice == '1':
        identifier = prompt('邮箱', required=True)
        password = prompt_secret('密码', required=True)
        _interactive_after_login(app, app.email_login(identifier, password))
        echo(format_status(app.status()))
    elif choice == '2':
        phone = prompt('手机号', required=True)
        request = app.request_phone_sms(phone)
        print_result(request)
        if request.get('status') == 'success':
            code = prompt('短信验证码', required=True)
            _interactive_after_login(app, app.phone_login(phone, code))
    elif choice == '3':
        ticket = prompt('ticket', default=app.pending_ticket, required=True)
        print_result(app.confirm_verification(ticket))
    elif choice == '4':
        result = app.realname_check()
        print_result(result)
        echo(f"结论: {STATE_LABEL.get(result.get('realname_state'), result.get('realname_state'))}")
    elif choice == '5':
        echo('注意：必须使用本人真实合法的身份信息。')
        realname = prompt('实名姓名', required=True)
        id_num = prompt_secret('证件号', required=True)
        if confirm(f"确认提交（{mask_realname(realname)} / {mask_id_num(id_num)}）？"):
            print_result(app.realname_submit(realname, id_num))
        else:
            echo('已取消。')
    elif choice == '6':
        print_result(app.mailbox())
    elif choice == '7':
        label = prompt('导出标签', default='restored_session')
        print_result(app.export_restored(label))
    elif choice == '8':
        if confirm('确认重建本机设备信息（会重新注册设备）？'):
            print_result(app.rebuild_device())
    elif choice == '9':
        echo(format_status(app.status()))
    elif choice == '10':
        echo('批量用法: python main.py batch-realname --input accounts.json [--submit]')
        echo('默认只审查；确认无误后再加 --submit。')
    else:
        echo('无效选择，请重新输入。')


def run_interactive(app):
    if not is_interactive():
        echo('当前非交互环境。请使用子命令，例如: python main.py status')
        echo('查看全部用法: python main.py --help')
        return 2
    echo('网易邮箱 / Cookie 控制台')
    while True:
        echo()
        echo('=== 主菜单 ===')
        for key, label in MENU:
            echo(f'  {key:>2}) {label}')
        try:
            choice = input('请选择: ').strip()
        except EOFError:
            echo()
            return 0
        if choice in ('0', 'q', 'quit', 'exit'):
            echo('再见。')
            return 0
        try:
            _interactive_dispatch(app, choice)
        except KeyboardInterrupt:
            echo()
            echo('已取消当前操作。')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # batch-realname 的参数直接透传给 batch_realname.py，避免 argparse 的 REMAINDER 陷阱。
    if argv and argv[0] == 'batch-realname':
        rest = argv[1:]
        if not rest:
            echo('用法: python main.py batch-realname --input accounts.json [--submit] [--delay 2]')
            return 2
        return batch_realname.main(rest)

    parser = build_parser()
    args = parser.parse_args(argv)
    app = ConsoleApp()

    if not args.command:
        return run_interactive(app)

    handler = COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(app, args) or 0
    except KeyboardInterrupt:
        echo()
        echo('已中断。')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
