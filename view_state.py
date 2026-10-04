#!/usr/bin/env python3
# -*- coding: utf-8 -*-


def get_ui_state(snapshot, pending_ticket, pending_phone, mode, identifier=''):
    has_session = bool(snapshot.get('sessionid_present'))
    has_sdkuid = bool(snapshot.get('sdkuid'))
    has_device_key = bool(snapshot.get('device_key_present'))
    restored = snapshot.get('restored_session') or {}
    restored_session = bool(restored.get('has_sauth'))
    need_verify = bool(pending_ticket)
    waiting_sms_code = mode == 'phone' and bool(pending_phone) and not (has_session and has_sdkuid)
    is_authenticated = has_session and has_sdkuid
    current_conversion_complete = bool(snapshot.get('current_conversion_complete'))
    restored_session_exported = bool(snapshot.get('restored_session_exported'))
    return {
        'mode': mode,
        'has_session': has_session,
        'has_sdkuid': has_sdkuid,
        'has_device_key': has_device_key,
        'need_verify': need_verify,
        'restored_session': restored_session,
        'is_authenticated': is_authenticated,
        'waiting_sms_code': waiting_sms_code,
        'identifier': identifier or pending_phone or '-',
        'show_advanced': is_authenticated or has_device_key,
        'can_export': current_conversion_complete,
        'can_export_restored': restored_session and not current_conversion_complete,
        'current_conversion_complete': current_conversion_complete,
        'restored_session_exported': restored_session_exported,
    }


def visible_actions(state):
    need_verify = state['need_verify']
    is_authenticated = state['is_authenticated']
    mode = state['mode']
    return {
        'start_login': not need_verify,
        'submit_code': mode == 'phone',
        'send_verify_sms': need_verify,
        'confirm_verify': need_verify,
        'open_verify_url': need_verify,
        'fetch_mailbox': is_authenticated,
        'save_artifacts': state['can_export'],
        'export_restored': state['can_export_restored'],
        'rebuild_device': state['show_advanced'],
        'load_cookies': state['show_advanced'],
        'ticket': mode == 'email' and need_verify,
        'advanced_section': state['show_advanced'],
        'advanced_hint': state['show_advanced'],
    }


def primary_action_label(state):
    if state['need_verify']:
        return '继续验证'
    if state['mode'] == 'phone':
        return '开始转换 / 请求短信'
    return '开始转换'


def secondary_action_label(state):
    if state['mode'] == 'phone':
        return '提交验证码并生成 Cookie'
    return '导出结果'


def build_summary_text(snapshot, state, pending_ticket):
    mode = '手机号转换' if state['mode'] == 'phone' else '邮箱转换'
    cookie_count = snapshot.get('cookie_count', 0)

    if state['need_verify']:
        phase = '等待安全验证完成'
    elif state['current_conversion_complete']:
        phase = '已生成可复用 Cookie'
    elif state['is_authenticated'] and state['restored_session']:
        phase = '已恢复旧会话'
    elif state['is_authenticated']:
        phase = '会话已加载，等待转换动作'
    elif state['waiting_sms_code']:
        phase = '等待短信验证码'
    elif state['has_device_key']:
        phase = '正在建立设备上下文'
    else:
        phase = '等待输入账号信息'

    lines = [
        f'当前模式: {mode}',
        f'转换进度: {phase}',
        f"目标账号: {state['identifier']}",
        '',
        f"Cookie会话: {'已生成' if state['current_conversion_complete'] else '未生成'}",
        f"SAuth会话: {'已生成' if state['current_conversion_complete'] else '未生成'}",
        f"已恢复旧会话: {'是' if state['restored_session'] else '否'}",
        f"本地Cookies数量: {cookie_count}",
        f"待处理Ticket: {pending_ticket or '-'}",
        f"可导出本次产物: {'是' if state['can_export'] else '否'}",
    ]
    if state['show_advanced']:
        lines.extend([
            '',
            '技术上下文:',
            f"- device_id: {snapshot.get('device_id') or '-'}",
            f"- 设备密钥: {'已加载' if state['has_device_key'] else '未加载'}",
        ])
    return '\n'.join(lines)


def summarize_result(data):
    if not isinstance(data, dict):
        return []

    lines = []
    phase = data.get('phase')
    if phase:
        phase_map = {
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
        lines.append(f"阶段: {phase_map.get(phase, phase)}")

    verify_state = data.get('verify_state')
    if verify_state == 'verify_required':
        lines.append('1351状态: 需要进入安全验证流程')
    elif verify_state == 'verify_pending':
        lines.append('1351状态: 验证尚未完成')
    elif verify_state == 'verify_manual_only':
        lines.append('1351状态: 已回退为人工验证')
    elif verify_state == 'verify_resolved':
        lines.append('1351状态: 验证已完成')

    if data.get('conversion_complete'):
        lines.append('转换结果: Cookie / SAuth 已可复用')

    if data.get('result_kind') == 'cookie_generated':
        lines.append('核心产物: 已生成认证产物')
    elif data.get('result_kind') == 'mailbox':
        lines.append('附属校验: 已请求邮箱列表')

    if data.get('ticket'):
        lines.append(f"Ticket: {data['ticket']}")
    if data.get('phone_number'):
        lines.append(f"手机号: {data['phone_number']}")
    if data.get('verify_url'):
        lines.append('需要访问验证链接继续')

    artifacts = data.get('artifacts') or {}
    if artifacts:
        saved = []
        paths = []
        for name, result in artifacts.items():
            if isinstance(result, dict) and result.get('status') == 'success':
                saved.append(name)
                if result.get('path'):
                    paths.append(result['path'])
        if saved:
            lines.append(f"已保存产物: {', '.join(saved)}")
        if paths:
            lines.append(f"保存位置: {paths[0]}")

    export_paths = data.get('export_paths') or []
    if export_paths:
        lines.append(f"导出目录: {export_paths[0]}")

    mailbox = data.get('mailbox') or {}
    messages = mailbox.get('messages') or []
    if isinstance(messages, list) and messages:
        lines.append(f'邮件数量: {len(messages)}')

    diagnostic = data.get('diagnostic') or {}
    if diagnostic.get('content_type'):
        lines.append(f"响应类型: {diagnostic['content_type']}")
    if diagnostic.get('text_preview'):
        lines.append('响应不是稳定 JSON，已降级人工验证')

    error = data.get('error')
    if isinstance(error, dict):
        reason = error.get('reason') or error.get('message')
        if reason:
            lines.append(f'失败原因: {reason}')
    elif isinstance(error, str) and error:
        lines.append(f'失败原因: {error}')

    if data.get('error_code'):
        lines.append(f"错误码: {data['error_code']}")
    if data.get('error_reason'):
        lines.append(f"错误原因: {data['error_reason']}")

    return lines[:8]
