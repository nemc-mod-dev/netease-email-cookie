#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading


class AuthWorkflow:
    def __init__(self, auth_service):
        self.auth = auth_service
        self.auto_poll_enabled = True
        self.auto_restore_enabled = True
        self._poll_timer = None

    def restore_previous_session(self):
        snapshot = self.auth.get_state_snapshot().get('restored_session', {})
        if snapshot.get('has_sauth'):
            return {'status': 'success', 'message': '已恢复旧会话', 'restored': snapshot, 'phase': 'session_restored'}
        return {'status': 'idle', 'message': '未发现可恢复会话', 'restored': snapshot, 'phase': 'idle'}

    def run_email_login(self, email, password):
        prepare = self.auth.prepare_device()
        if prepare['status'] != 'success':
            prepare['phase'] = 'preparing_device'
            return prepare

        result = self.auth.login_email(email, password)
        if result['status'] == 'success':
            result['phase'] = 'artifacts_ready'
            result['conversion_complete'] = True
            result['result_kind'] = 'cookie_generated'
        elif result['status'] == 'need_verify':
            result['phase'] = 'waiting_verify'
            result['verify_state'] = result.get('verify_state', 'verify_required')
        else:
            result['phase'] = 'logging_in'
        return result

    def request_phone_sms(self, phone_number):
        result = self.auth.request_phone_login_sms(phone_number)
        result['phase'] = 'waiting_sms_code' if result['status'] == 'success' else 'requesting_sms'
        return result

    def complete_phone_login(self, phone_number, verify_code):
        prepare = self.auth.prepare_device()
        if prepare['status'] != 'success':
            prepare['phase'] = 'preparing_device'
            return prepare

        result = self.auth.login_phone(phone_number, verify_code)
        if result['status'] == 'success':
            result['phase'] = 'artifacts_ready'
            result['conversion_complete'] = True
            result['result_kind'] = 'cookie_generated'
        else:
            result['phase'] = 'logging_in'
        return result

    def confirm_verification(self, ticket, label=None):
        result = self.auth.verify_with_ticket(ticket, label)
        if result['status'] == 'success':
            result['phase'] = 'artifacts_ready'
            result['conversion_complete'] = True
            result['result_kind'] = 'cookie_generated'
        else:
            result['phase'] = result.get('phase', 'waiting_verify')
            result['verify_state'] = result.get('verify_state', 'verify_pending')
        return result

    def fetch_mailbox(self):
        result = self.auth.get_mailbox_list()
        result['phase'] = 'fetching_mailbox'
        result['result_kind'] = 'mailbox'
        return result

    def export_artifacts(self, label):
        result = self.auth.save_all_artifacts(label)
        result['phase'] = 'artifacts_ready'
        result['result_kind'] = 'cookie_generated'
        result['conversion_complete'] = result.get('status') == 'success'
        return result

    def start_verify_polling(self, ticket, on_update=None, interval=5):
        if not self.auto_poll_enabled or not ticket:
            return {'status': 'idle', 'message': '未开启自动轮询或缺少 ticket', 'phase': 'waiting_verify'}
        self.stop_verify_polling()

        def poll_once():
            status = self.auth.check_verification_status(ticket)
            status['phase'] = status.get('phase', 'polling_verify')
            if on_update:
                on_update(status)
            if status.get('status') in ('manual_required', 'success') or status.get('verify_state') in ('verify_manual_only', 'verify_resolved'):
                self._poll_timer = None
                return
            self._poll_timer = threading.Timer(interval, poll_once)
            self._poll_timer.daemon = True
            self._poll_timer.start()

        self._poll_timer = threading.Timer(interval, poll_once)
        self._poll_timer.daemon = True
        self._poll_timer.start()
        return {'status': 'success', 'message': '已启动验证状态轮询', 'ticket': ticket, 'phase': 'polling_verify'}

    def stop_verify_polling(self):
        if self._poll_timer:
            self._poll_timer.cancel()
            self._poll_timer = None
            return {'status': 'success', 'message': '已停止验证状态轮询', 'phase': 'idle'}
        return {'status': 'idle', 'message': '当前没有进行中的验证轮询', 'phase': 'idle'}
