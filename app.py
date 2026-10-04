#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import subprocess
import threading

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static

from services.auth_service import NetEaseAuthService
from view_state import (
    build_summary_text,
    get_ui_state,
    primary_action_label,
    secondary_action_label,
    summarize_result,
    visible_actions,
)
from workflow import AuthWorkflow


class NetEaseCookieTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #body { layout: horizontal; height: 1fr; }
    #left { width: 42; min-width: 42; padding: 1; border: solid $accent; overflow-y: auto; }
    #right { padding: 1; border: solid $primary; overflow: hidden; }
    .section-title { margin-top: 1; margin-bottom: 1; text-style: bold; color: $accent; }
    .hint { color: $text-muted; margin-bottom: 1; }
    .advanced { color: $warning; }
    Button { width: 1fr; margin-top: 1; }
    Input, Select { margin-top: 1; }
    #summary { height: 14; border: solid $panel; padding: 1; overflow: hidden auto; }
    #log { height: 1fr; border: solid $panel; }
    """

    BINDINGS = [('q', 'quit', '退出'), ('r', 'refresh_summary', '刷新状态')]

    def __init__(self):
        super().__init__()
        self.auth = NetEaseAuthService()
        self.workflow = AuthWorkflow(self.auth)
        self.pending_ticket = ''
        self.pending_phone = ''
        self.pending_verify_url = ''

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id='body'):
            with Vertical(id='left'):
                yield Static('转换模式', classes='section-title')
                yield Select([('邮箱转 Cookie', 'email'), ('手机号转 Cookie', 'phone')], value='email', id='mode')

                yield Static('账号信息输入', classes='section-title')
                yield Static('输入账号侧信息，系统会自动推进到 Cookie / SAuth 产物。', id='mode_hint', classes='hint')
                yield Input(placeholder='请输入邮箱', id='identifier')
                yield Input(password=True, placeholder='请输入密码', id='secret')
                yield Input(placeholder='安全验证 ticket', id='ticket')

                yield Static('主流程', classes='section-title')
                yield Button('开始转换', id='start_login', variant='success')
                yield Button('继续验证', id='confirm_verify', variant='primary')
                yield Button('打开验证链接', id='open_verify_url')
                yield Button('提交验证码并生成 Cookie', id='submit_code')
                yield Button('导出结果', id='save_artifacts')
                yield Button('重新导出已恢复会话', id='export_restored')

                yield Static('高级操作', id='advanced_section', classes='section-title advanced')
                yield Static('以下操作用于排障或会话校验，不属于主转换链路。', id='advanced_hint', classes='hint')
                yield Button('发送安全验证短信', id='send_verify_sms')
                yield Button('获取邮件列表', id='fetch_mailbox')
                yield Button('重建设备', id='rebuild_device', variant='warning')
                yield Button('加载 cookies.json', id='load_cookies')
                yield Button('刷新状态', id='refresh_summary')

            with Vertical(id='right'):
                yield Static('转换状态', classes='section-title')
                yield Static(id='summary')
                yield Static('事件日志', classes='section-title')
                yield RichLog(id='log', highlight=True, markup=False, wrap=True)
        yield Footer()

    def on_mount(self):
        self.update_mode_fields()
        restored = self.workflow.restore_previous_session()
        self.refresh_summary()
        self.refresh_action_visibility()
        self.refresh_button_labels()
        self.write_log('转换器已启动。', restored)
        if restored.get('status') == 'success':
            self.write_log('检测到本地已有可复用会话，可直接导出或校验。', restored)

    def action_refresh_summary(self):
        self.refresh_summary()
        self.refresh_action_visibility()
        self.refresh_button_labels()

    def current_mode(self):
        return self.query_one('#mode', Select).value or 'email'

    def identifier(self):
        return self.query_one('#identifier', Input).value.strip()

    def secret(self):
        return self.query_one('#secret', Input).value.strip()

    def ticket(self):
        typed_ticket = self.query_one('#ticket', Input).value.strip()
        return typed_ticket or self.pending_ticket

    def ui_state(self):
        return get_ui_state(self.auth.get_state_snapshot(), self.pending_ticket, self.pending_phone, self.current_mode(), self.identifier())

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == 'mode':
            self.update_mode_fields()
            self.refresh_summary()
            self.refresh_action_visibility()
            self.refresh_button_labels()

    def update_mode_fields(self):
        mode = self.current_mode()
        identifier = self.query_one('#identifier', Input)
        secret = self.query_one('#secret', Input)
        hint = self.query_one('#mode_hint', Static)
        ticket = self.query_one('#ticket', Input)
        if mode == 'phone':
            identifier.placeholder = '请输入手机号'
            secret.placeholder = '请输入短信验证码'
            hint.update('输入手机号后开始转换；收到验证码后提交，即可生成 Cookie / SAuth。')
            ticket.placeholder = '手机号模式通常无需手填 ticket'
        else:
            identifier.placeholder = '请输入邮箱'
            secret.placeholder = '请输入密码'
            hint.update('输入邮箱和密码后开始转换；如触发安全验证，再继续完成验证。')
            ticket.placeholder = '仅在邮箱安全验证阶段使用'

    def refresh_button_labels(self):
        state = self.ui_state()
        self.query_one('#start_login', Button).label = primary_action_label(state)
        self.query_one('#submit_code', Button).label = secondary_action_label(state)

    def refresh_action_visibility(self):
        state = self.ui_state()
        actions = visible_actions(state)
        for widget_id, visible in actions.items():
            self.query_one(f'#{widget_id}').display = visible

    def refresh_summary(self):
        snapshot = self.auth.get_state_snapshot()
        state = self.ui_state()
        self.query_one('#summary', Static).update(build_summary_text(snapshot, state, self.pending_ticket))

    def write_log(self, message, data=None):
        logger = self.query_one('#log', RichLog)
        logger.write(f'• {message}')
        for line in summarize_result(data):
            logger.write(f'  {line}')

    def open_verify_url(self):
        verify_url = self.pending_verify_url
        if not verify_url:
            return {'status': 'failed', 'message': '当前没有可打开的验证链接'}

        commands = []
        if shutil.which('termux-open-url'):
            commands.append(['termux-open-url', verify_url])
        if shutil.which('xdg-open'):
            commands.append(['xdg-open', verify_url])

        for command in commands:
            try:
                subprocess.Popen(command)
                return {'status': 'success', 'message': '已尝试在浏览器中打开验证链接', 'verify_url': verify_url, 'command': ' '.join(command)}
            except Exception as e:
                last_error = str(e)
        return {'status': 'manual_required', 'message': '无法自动打开浏览器，请手动打开验证链接', 'verify_url': verify_url, 'error': locals().get('last_error', 'no opener available')}

    def handle_verify_poll_update(self, status):
        def _update():
            self.write_log('验证状态已更新。', status)
            if status.get('verify_state') == 'verify_manual_only' or status.get('status') == 'manual_required':
                self.workflow.stop_verify_polling()
                self.write_log('自动轮询不可靠，已回退为手动完成安全验证。', status)
                self.refresh_summary()
                self.refresh_action_visibility()
                self.refresh_button_labels()
                return

            data = status.get('data') or {}
            if status.get('verify_state') == 'verify_resolved' or (isinstance(data, dict) and data.get('user')):
                ticket = self.ticket()
                result = self.workflow.confirm_verification(ticket, self.identifier() or self.pending_phone or 'verified_account')
                self.workflow.stop_verify_polling()
                self.handle_auth_result(result)
                return

            self.refresh_summary()
            self.refresh_action_visibility()
            self.refresh_button_labels()

        self.call_from_thread(_update)

    def handle_auth_result(self, result):
        self.write_log(result['message'], result)
        if result['status'] == 'need_verify':
            self.pending_ticket = result.get('ticket', '') or ''
            self.pending_verify_url = result.get('verify_url', '') or self.pending_verify_url
            poll = self.workflow.start_verify_polling(self.pending_ticket, self.handle_verify_poll_update)
            self.write_log(poll['message'], poll)
        elif result.get('verify_state') == 'verify_manual_only' or result['status'] == 'manual_required':
            self.pending_ticket = result.get('ticket', self.pending_ticket) or self.pending_ticket
            self.pending_verify_url = result.get('verify_url', self.pending_verify_url) or self.pending_verify_url
            self.workflow.stop_verify_polling()
        elif result['status'] == 'success':
            self.pending_ticket = result.get('ticket', '') or ''
            self.pending_verify_url = result.get('verify_url', self.pending_verify_url) or self.pending_verify_url
            if result.get('conversion_complete'):
                self.write_log('转换主链已自动收尾，认证产物已可复用。', result)
        elif result['status'] in ('failed', 'error') and self.current_mode() == 'email':
            self.pending_ticket = ''
        self.refresh_summary()
        self.refresh_action_visibility()
        self.refresh_button_labels()

    def on_button_pressed(self, event: Button.Pressed):
        button_id = event.button.id
        if button_id == 'start_login':
            self.handle_start_login()
        elif button_id == 'submit_code':
            self.handle_submit_code()
        elif button_id == 'send_verify_sms':
            ticket = self.ticket()
            if not ticket:
                self.write_log('缺少 ticket。')
            else:
                result = self.auth.send_verify_sms(ticket)
                self.write_log(result['message'], result)
        elif button_id == 'open_verify_url':
            result = self.open_verify_url()
            self.write_log(result['message'], result)
        elif button_id == 'confirm_verify':
            ticket = self.ticket()
            if not ticket:
                self.write_log('缺少 ticket。')
            else:
                result = self.workflow.confirm_verification(ticket, self.identifier() or self.pending_phone or 'verified_account')
                self.workflow.stop_verify_polling()
                self.handle_auth_result(result)
        elif button_id == 'fetch_mailbox':
            result = self.workflow.fetch_mailbox()
            self.write_log(result['message'], result)
        elif button_id == 'save_artifacts':
            label = self.identifier() or self.pending_phone or self.auth.get_state_snapshot().get('current_conversion_label') or 'account'
            result = self.workflow.export_artifacts(label)
            self.write_log(result['message'], result)
        elif button_id == 'export_restored':
            label = self.identifier() or self.pending_phone or 'restored_session'
            result = self.auth.export_restored_session(label)
            self.write_log(result['message'], result)
        elif button_id == 'rebuild_device':
            result = self.auth.rebuild_device()
            self.write_log(result['message'], result)
        elif button_id == 'load_cookies':
            result = self.auth.load_cookies()
            self.write_log(result['message'], result)
        elif button_id == 'refresh_summary':
            self.write_log('状态已刷新。')
        self.refresh_summary()
        self.refresh_action_visibility()
        self.refresh_button_labels()

    def handle_start_login(self):
        mode = self.current_mode()
        identifier = self.identifier()
        secret = self.secret()
        if not identifier:
            self.write_log('请先输入邮箱或手机号。')
            return
        if mode == 'email':
            if not secret:
                self.write_log('请先输入密码。')
                return
            result = self.workflow.run_email_login(identifier, secret)
            self.handle_auth_result(result)
        else:
            self.pending_phone = identifier
            result = self.workflow.request_phone_sms(identifier)
            self.write_log(result['message'], result)
            self.refresh_summary()
            self.refresh_action_visibility()
            self.refresh_button_labels()

    def handle_submit_code(self):
        mode = self.current_mode()
        identifier = self.identifier() or self.pending_phone
        secret = self.secret()
        if mode == 'phone':
            if not identifier or not secret:
                self.write_log('手机号转换需要手机号和短信验证码。')
                return
            result = self.workflow.complete_phone_login(identifier, secret)
            self.handle_auth_result(result)
            return
        self.write_log('当前模式无需提交短信验证码。')
