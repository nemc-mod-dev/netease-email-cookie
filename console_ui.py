#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯控制台的输出格式化与输入辅助。不依赖任何第三方库。"""

import getpass
import json
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
    """用于密码等敏感输入（尽量不回显）。"""
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


_PHASE_LABELS = {
    'session_restored': '已恢复可复用会话',
    'preparing_device': '设备上下文准备中',
    'requesting_sms': '正在请求短信验证码',
    'waiting_sms_code': '等待输入短信验证码',
    'logging_in': '正在生成会话',
    'waiting_verify': '等待完成安全验证',
    'polling_verify': '正在轮询验证状态',
    'verify_manual_only': '需要人工完成安全验证',
    'verify_resolved': '验证已完成，正在生成会话',
    'verify_failed': '安全验证未通过',
    'artifacts_ready': '已生成认证产物',
    'fetching_mailbox': '正在校验会话可用性',
    'idle': '等待下一步操作',
}


def summarize_result(result, limit=12):
    """把服务层返回的 dict 拆成可读行，供控制台打印。"""
    if not isinstance(result, dict):
        return []

    lines = []
    phase = result.get('phase')
    if phase:
        lines.append(f"阶段: {_PHASE_LABELS.get(phase, phase)}")

    verify_state = result.get('verify_state')
    verify_map = {
        'verify_required': '需要进入安全验证流程',
        'verify_pending': '验证尚未完成',
        'verify_manual_only': '已回退为人工验证',
        'verify_resolved': '验证已完成',
    }
    if verify_state in verify_map:
        lines.append(f"1351状态: {verify_map[verify_state]}")

    if result.get('conversion_complete'):
        lines.append('转换结果: Cookie / SAuth 已可复用')
    if result.get('result_kind') == 'cookie_generated':
        lines.append('核心产物: 已生成认证产物')
    elif result.get('result_kind') == 'mailbox':
        lines.append('附属校验: 已请求邮箱列表')

    if result.get('ticket'):
        lines.append(f"Ticket: {result['ticket']}")
    if result.get('phone_number'):
        lines.append(f"手机号: {result['phone_number']}")
    if result.get('verify_url'):
        lines.append(f"验证链接: {result['verify_url']}")

    artifacts = result.get('artifacts') or {}
    if artifacts:
        saved, paths = [], []
        for name, item in artifacts.items():
            if isinstance(item, dict) and item.get('status') == 'success':
                saved.append(name)
                if item.get('path'):
                    paths.append(item['path'])
                nested = item.get('nemc')
                if isinstance(nested, dict) and nested.get('path'):
                    paths.append(nested['path'])
        if saved:
            lines.append(f"已保存产物: {', '.join(saved)}")
        if paths:
            lines.append(f"产物目录: {paths[0]}")

    export_paths = result.get('export_paths') or []
    if export_paths:
        lines.append(f"导出目录: {export_paths[0]}")

    mailbox = result.get('mailbox') or {}
    messages = mailbox.get('messages') if isinstance(mailbox, dict) else None
    if isinstance(messages, list) and messages:
        lines.append(f"邮件数量: {len(messages)}")

    realname_state = result.get('realname_state')
    if realname_state:
        lines.append(f"实名状态: {realname_state}")
    if result.get('needs_realname') is not None:
        lines.append(f"需要实名: {'是' if result['needs_realname'] else '否'}")
    if result.get('realname_status') is not None:
        lines.append(f"realname_status: {result['realname_status']}")
    if result.get('need_aas') is not None:
        lines.append(f"need_aas: {result['need_aas']}")
    if result.get('realname_type'):
        lines.append(f"实名类型: {result['realname_type']}")

    diagnostic = result.get('diagnostic') or {}
    if diagnostic.get('text_preview'):
        lines.append('响应不是稳定 JSON，已降级人工验证')

    error = result.get('error')
    if isinstance(error, dict):
        reason = error.get('reason') or error.get('message')
        if reason:
            lines.append(f'失败原因: {reason}')
    elif isinstance(error, str) and error:
        lines.append(f'失败原因: {error}')
    if result.get('error_code'):
        lines.append(f"错误码: {result['error_code']}")
    if result.get('error_reason'):
        lines.append(f"错误原因: {result['error_reason']}")

    return lines[:limit]


def print_result(result, verbose=False):
    if not isinstance(result, dict):
        echo(f'• {result}')
        return
    echo(f"• {result.get('message', '')}  (status={result.get('status', '?')})")
    for line in summarize_result(result):
        echo(f'  {line}')
    if verbose:
        echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def format_status(snapshot):
    """把状态快照格式化成控制台可读文本。"""
    if not isinstance(snapshot, dict):
        return '无状态信息'
    restored = snapshot.get('restored_session') or {}
    lines = [
        f"设备ID: {snapshot.get('device_id') or '-'}",
        f"设备密钥: {'已加载' if snapshot.get('device_key_present') else '未加载'}",
        f"SDK UID: {snapshot.get('sdkuid') or '-'}",
        f"会话(sessionid): {'有效' if snapshot.get('sessionid_present') else '无'}",
        f"HTTP Cookies: {snapshot.get('cookie_count', 0)} 个",
        f"可恢复旧会话: {'是' if restored.get('has_sauth') else '否'}",
        f"本次转换完成: {'是' if snapshot.get('current_conversion_complete') else '否'}",
        f"转换账号: {snapshot.get('current_conversion_label') or '-'}",
    ]
    last_verify = snapshot.get('last_verify_context') or {}
    if last_verify.get('ticket'):
        lines.append(f"待处理 Ticket: {last_verify['ticket']}")
    return '\n'.join(lines)


def is_interactive():
    return sys.stdin is not None and sys.stdin.isatty()
