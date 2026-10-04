#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

from urllib.parse import parse_qs, urlparse


VERIFY_REQUIRED = 'verify_required'
VERIFY_PENDING = 'verify_pending'
VERIFY_MANUAL_ONLY = 'verify_manual_only'
VERIFY_RESOLVED = 'verify_resolved'


def _json_or_diagnostic(response):
    content_type = response.headers.get('content-type', '')
    text = response.text or ''
    try:
        return {'ok': True, 'data': response.json(), 'content_type': content_type, 'text_preview': text[:200]}
    except json.JSONDecodeError as e:
        return {
            'ok': False,
            'content_type': content_type,
            'text_preview': text[:200],
            'parse_error': str(e),
            'status_code': response.status_code,
        }


def _verify_state_payload(verify_state, message, **kwargs):
    payload = {'verify_state': verify_state, 'message': message}
    payload.update(kwargs)
    return payload


def _extract_user_candidate(data):
    if isinstance(data, dict) and data.get('user'):
        return data['user']
    return None


def _infer_verify_state_from_data(data):
    if not isinstance(data, dict):
        return None
    if data.get('user'):
        return VERIFY_RESOLVED
    if data.get('code') == 1351:
        return VERIFY_PENDING
    return None


def _polling_manual_fallback(message, diagnostic=None):
    payload = {
        'status': 'manual_required',
        'verify_state': VERIFY_MANUAL_ONLY,
        'message': message,
    }
    if diagnostic:
        payload['diagnostic'] = diagnostic
    return payload


def _pending_payload(message, data=None):
    payload = {
        'status': 'pending',
        'verify_state': VERIFY_PENDING,
        'message': message,
    }
    if data is not None:
        payload['data'] = data
    return payload


def _resolved_payload(message, user_info=None, token=None, data=None):
    payload = {
        'status': 'success',
        'verify_state': VERIFY_RESOLVED,
        'message': message,
    }
    if user_info is not None:
        payload['user_info'] = user_info
    if token is not None:
        payload['token'] = token
    if data is not None:
        payload['data'] = data
    return payload


def _required_payload(message, **kwargs):
    payload = {
        'status': 'need_verify',
        'verify_state': VERIFY_REQUIRED,
        'message': message,
    }
    payload.update(kwargs)
    return payload


def _error_payload(message, error=None, diagnostic=None):
    payload = {'status': 'error', 'message': message, 'verify_state': VERIFY_MANUAL_ONLY}
    if error is not None:
        payload['error'] = error
    if diagnostic is not None:
        payload['diagnostic'] = diagnostic
    return payload


def _failed_payload(message, error=None):
    payload = {'status': 'failed', 'message': message}
    if error is not None:
        payload['error'] = error
    return payload


def _success_payload(message, data=None):
    payload = {'status': 'success', 'message': message}
    if data is not None:
        payload['data'] = data
    return payload


def _normalize_status_payload(response):
    parsed = _json_or_diagnostic(response)
    if not parsed['ok']:
        return _polling_manual_fallback('轮询响应不是稳定 JSON，已回退为手动验证', parsed)
    data = parsed['data']
    verify_state = _infer_verify_state_from_data(data)
    if verify_state == VERIFY_RESOLVED:
        user = _extract_user_candidate(data)
        return _resolved_payload('验证状态已完成', user_info=user, token=(user or {}).get('token'), data=data)
    if verify_state == VERIFY_PENDING:
        return _pending_payload(data.get('reason', '验证尚未完成'), data=data)
    return _polling_manual_fallback('轮询接口返回了无法自动判断的状态，建议手动完成验证', {'data': data, 'content_type': parsed['content_type'], 'text_preview': parsed['text_preview']})


def _normalize_submit_payload(response):
    parsed = _json_or_diagnostic(response)
    if not parsed['ok']:
        return _error_payload('提交验证结果异常', error=parsed['parse_error'], diagnostic=parsed)
    data = parsed['data']
    user = _extract_user_candidate(data)
    if user and user.get('token'):
        return _resolved_payload('验证成功', user_info=user, token=user.get('token'), data=data)
    if data.get('code') == 1351:
        return _pending_payload(data.get('reason', '验证尚未完成'), data=data)
    return _failed_payload(data.get('reason', '验证失败'), error=data)


def _normalize_send_sms_payload(response):
    parsed = _json_or_diagnostic(response)
    if not parsed['ok']:
        return _error_payload('短信验证码发送异常', error=parsed['parse_error'], diagnostic=parsed)
    data = parsed['data']
    if data.get('code') == 200:
        return _success_payload('短信验证码已发送', data=data)
    return _failed_payload(data.get('reason', '短信验证码发送失败'), error=data)


def _extract_verify_context(parsed, identifier):
    ticket = parsed.get('ticket')
    if not ticket:
        return {
            'status': 'manual_required',
            'verify_state': VERIFY_MANUAL_ONLY,
            'message': '无法从验证链接中提取 ticket',
            'identifier': identifier,
            **parsed,
        }
    return {
        'status': 'need_verify',
        'verify_state': VERIFY_REQUIRED,
        'message': '需要完成安全验证',
        'identifier': identifier,
        **parsed,
    }


def _verify_error_code(data):
    if isinstance(data, dict):
        return data.get('code')
    return None


def _verify_reason(data, default='验证失败'):
    if isinstance(data, dict):
        return data.get('reason', default)
    return default


def _status_with_code(payload, data):
    code = _verify_error_code(data)
    if code is not None:
        payload['error_code'] = code
    reason = _verify_reason(data, payload.get('message', '验证失败'))
    if reason:
        payload['error_reason'] = reason
    return payload


def _manual_required_from_response(message, response):
    return _polling_manual_fallback(message, {
        'status_code': response.status_code,
        'content_type': response.headers.get('content-type', ''),
        'text_preview': (response.text or '')[:200],
    })


def _normalize_login_1351(result, verify_info):
    payload = _required_payload(
        '需要完成安全验证',
        verify_url=verify_info.get('verify_url'),
        ticket=verify_info.get('ticket'),
        code=verify_info.get('code'),
        guide=verify_info,
    )
    return _status_with_code(payload, result)


def _normalize_submit_pending(result):
    return _status_with_code(_pending_payload(_verify_reason(result, '验证尚未完成'), data=result), result)


def _normalize_status_pending(result):
    return _status_with_code(_pending_payload(_verify_reason(result, '验证尚未完成'), data=result), result)


def _normalize_failed_result(result, default='验证失败'):
    return _status_with_code(_failed_payload(_verify_reason(result, default), error=result), result)


def _normalize_non_json_error(message, response, exception):
    return _error_payload(message, error=str(exception), diagnostic={
        'status_code': response.status_code,
        'content_type': response.headers.get('content-type', ''),
        'text_preview': (response.text or '')[:200],
    })


def _response_json(response):
    return response.json()


def _has_verify_user(data):
    return bool(isinstance(data, dict) and data.get('user'))


def _verify_token(data):
    user = data.get('user') if isinstance(data, dict) else None
    return user.get('token') if isinstance(user, dict) else None


def _verify_user(data):
    return data.get('user') if isinstance(data, dict) else None


def _manual_required_for_polling(response, exception=None):
    diagnostic = {
        'status_code': response.status_code,
        'content_type': response.headers.get('content-type', ''),
        'text_preview': (response.text or '')[:200],
    }
    if exception is not None:
        diagnostic['parse_error'] = str(exception)
    return {
        'status': 'manual_required',
        'verify_state': VERIFY_MANUAL_ONLY,
        'message': '轮询接口返回不稳定，已回退为手动验证',
        'diagnostic': diagnostic,
    }


def _json_success(response):
    return _json_or_diagnostic(response)


def _status_payload(data):
    if _has_verify_user(data):
        user = _verify_user(data)
        return _resolved_payload('验证状态已完成', user_info=user, token=_verify_token(data), data=data)
    if _verify_error_code(data) == 1351:
        return _normalize_status_pending(data)
    return None


def _submit_payload(data):
    if _has_verify_user(data) and _verify_token(data):
        user = _verify_user(data)
        return _resolved_payload('验证成功', user_info=user, token=_verify_token(data), data=data)
    if _verify_error_code(data) == 1351:
        return _normalize_submit_pending(data)
    return _normalize_failed_result(data)


def _sms_payload(data):
    if isinstance(data, dict) and data.get('code') == 200:
        return _success_payload('短信验证码已发送', data=data)
    return _normalize_failed_result(data, '短信验证码发送失败')


def _content_debug(response):
    return {
        'status_code': response.status_code,
        'content_type': response.headers.get('content-type', ''),
        'text_preview': (response.text or '')[:200],
    }


def _with_diagnostic(payload, response):
    payload['diagnostic'] = _content_debug(response)
    return payload


def _json_checked(response, manual_message):
    try:
        return response.json(), None
    except json.JSONDecodeError as e:
        return None, _manual_required_for_polling(response, e)


def _manual_pending(message, data=None):
    payload = {'status': 'manual_required', 'verify_state': VERIFY_MANUAL_ONLY, 'message': message}
    if data is not None:
        payload['data'] = data
    return payload


def _verify_payload_from_status(data):
    if _verify_error_code(data) == 1351:
        return _normalize_status_pending(data)
    if _has_verify_user(data):
        user = _verify_user(data)
        return _resolved_payload('验证状态已完成', user_info=user, token=_verify_token(data), data=data)
    return _manual_pending('当前验证状态需要人工确认', data=data)


def _status_diagnostic_payload(response, data):
    payload = _verify_payload_from_status(data)
    if payload.get('status') == 'manual_required':
        return _with_diagnostic(payload, response)
    return payload


def _response_to_json_or_fallback(response, fallback_message):
    try:
        return response.json(), None
    except json.JSONDecodeError as e:
        return None, _manual_required_for_polling(response, e)


def _response_to_json_error(response, fallback_message):
    data, fallback = _response_to_json_or_fallback(response, fallback_message)
    if fallback is not None:
        fallback['message'] = fallback_message
    return data, fallback


def _verify_pending_message(data):
    return _verify_reason(data, '验证尚未完成')


def _login_verify_required_payload(result, verify_info):
    payload = _normalize_login_1351(result, verify_info)
    payload['phase'] = 'waiting_verify'
    return payload


def _poll_manual_payload(response, exception=None):
    return _manual_required_for_polling(response, exception)


def _poll_response_payload(response):
    data, fallback = _response_to_json_error(response, '轮询接口返回不稳定，已回退为手动验证')
    if fallback is not None:
        return fallback
    return _status_diagnostic_payload(response, data)


def _submit_response_payload(response):
    data, fallback = _response_to_json_error(response, '提交验证结果异常')
    if fallback is not None:
        fallback['status'] = 'error'
        return fallback
    return _submit_payload(data)


def _sms_response_payload(response):
    data, fallback = _response_to_json_error(response, '短信验证码发送异常')
    if fallback is not None:
        fallback['status'] = 'error'
        return fallback
    return _sms_payload(data)


def _verify_transition(status):
    return status in (VERIFY_REQUIRED, VERIFY_PENDING, VERIFY_MANUAL_ONLY, VERIFY_RESOLVED)


def _status_reason(data):
    return _verify_reason(data, '验证状态未知')


def _status_payload_with_phase(payload, phase):
    payload['phase'] = phase
    return payload


def _required_with_phase(verify_info):
    payload = _required_payload('需要完成安全验证', **verify_info)
    return _status_payload_with_phase(payload, 'waiting_verify')


def _status_to_manual_if_unknown(payload, response):
    if payload.get('status') == 'manual_required':
        return _with_diagnostic(payload, response)
    return payload


def _verify_pending_with_phase(data):
    return _status_payload_with_phase(_normalize_status_pending(data), 'waiting_verify')


def _verify_resolved_with_phase(user, data):
    return _status_payload_with_phase(_resolved_payload('验证状态已完成', user_info=user, token=user.get('token'), data=data), 'verify_resolved')


def _manual_with_phase(message, response=None, data=None):
    payload = _manual_pending(message, data=data)
    payload['phase'] = 'verify_manual_only'
    if response is not None:
        payload = _with_diagnostic(payload, response)
    return payload


def _pending_with_phase(data):
    payload = _normalize_submit_pending(data)
    payload['phase'] = 'waiting_verify'
    return payload


def _submit_success_with_phase(user, data):
    payload = _resolved_payload('验证成功', user_info=user, token=user.get('token'), data=data)
    payload['phase'] = 'verify_resolved'
    return payload


def _error_with_phase(message, error=None, diagnostic=None):
    payload = _error_payload(message, error=error, diagnostic=diagnostic)
    payload['phase'] = 'verify_manual_only'
    return payload


def _failed_with_phase(data):
    payload = _normalize_failed_result(data)
    payload['phase'] = 'verify_failed'
    return payload


def _sms_success_with_phase(data):
    payload = _success_payload('短信验证码已发送', data=data)
    payload['phase'] = 'waiting_verify'
    return payload


def _sms_failed_with_phase(data):
    payload = _normalize_failed_result(data, '短信验证码发送失败')
    payload['phase'] = 'verify_failed'
    return payload


def _verify_url_payload(parsed, identifier):
    if not parsed['ticket']:
        payload = {'status': 'manual_required', 'verify_state': VERIFY_MANUAL_ONLY, 'message': '无法从验证链接中提取 ticket', 'identifier': identifier, **parsed}
        payload['phase'] = 'verify_manual_only'
        return payload
    payload = {'status': 'need_verify', 'verify_state': VERIFY_REQUIRED, 'message': '需要完成安全验证', 'identifier': identifier, **parsed}
    payload['phase'] = 'waiting_verify'
    return payload


def _append_result_reason(payload, data):
    code = _verify_error_code(data)
    if code is not None:
        payload['error_code'] = code
    payload['error_reason'] = _verify_reason(data, payload.get('message', '验证失败'))
    return payload


def _status_json_to_payload(response, data):
    if _has_verify_user(data):
        return _verify_resolved_with_phase(_verify_user(data), data)
    if _verify_error_code(data) == 1351:
        return _verify_pending_with_phase(data)
    return _manual_with_phase('轮询接口返回了无法自动判断的状态，建议手动完成验证', response=response, data=data)


def _submit_json_to_payload(data):
    if _has_verify_user(data) and _verify_token(data):
        return _submit_success_with_phase(_verify_user(data), data)
    if _verify_error_code(data) == 1351:
        return _pending_with_phase(data)
    return _failed_with_phase(data)


def _sms_json_to_payload(data):
    if isinstance(data, dict) and data.get('code') == 200:
        return _sms_success_with_phase(data)
    return _sms_failed_with_phase(data)


class VerifyService:
    def __init__(self, session, device_payload_getter=None, headers_getter=None):
        self.session = session
        self.device_payload_getter = device_payload_getter
        self.headers_getter = headers_getter

    def _base_payload(self):
        if self.device_payload_getter:
            return self.device_payload_getter()
        return {'cv': 'a5.16.0', 'gv': '840287970', 'app_mode': '2', 'app_channel': 'netease'}

    def _headers(self):
        if self.headers_getter:
            return self.headers_getter()
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Requested-With': 'XMLHttpRequest',
        }

    def parse_verify_url(self, verify_url):
        parsed_url = urlparse(verify_url or '')
        params = parse_qs(parsed_url.query)
        return {
            'verify_url': verify_url,
            'code': params.get('code', [''])[0],
            'ticket': params.get('ticket', [''])[0],
            'chg_pwd': params.get('chg_pwd', ['0'])[0],
        }

    def handle_verification(self, verify_url, identifier=''):
        parsed = self.parse_verify_url(verify_url)
        return _verify_url_payload(parsed, identifier)

    def send_sms_code(self, ticket):
        url = 'https://service.mkey.163.com/mpay/api/reverify/send_sms'
        data = {'ticket': ticket, 'lang': '', **self._base_payload()}
        try:
            response = self.session.post(url, data=data, headers=self._headers(), timeout=30)
            return _sms_response_payload(response)
        except Exception as e:
            return _error_with_phase('短信验证码发送异常', error=str(e))

    def submit_verification_result(self, ticket, code='', chg_pwd='0'):
        url = 'https://service.mkey.163.com/mpay/api/reverify/upload_sms/result'
        data = {'ticket': ticket, 'lang': '', 'chg_pwd': chg_pwd, **self._base_payload()}
        if code:
            data['code'] = code
        try:
            response = self.session.post(url, data=data, headers=self._headers(), timeout=30)
            return _submit_response_payload(response)
        except Exception as e:
            return _error_with_phase('提交验证结果异常', error=str(e))

    def check_verification_status(self, ticket):
        url = 'https://service.mkey.163.com/mpay/api/reverify/check_status'
        data = {'ticket': ticket, **self._base_payload()}
        try:
            response = self.session.post(url, data=data, headers=self._headers(), timeout=30)
            return _poll_response_payload(response)
        except Exception as e:
            return _error_with_phase('检查验证状态失败', error=str(e))


def manual_verification_guide(verify_url, identifier):
    parsed_url = urlparse(verify_url or '')
    return {
        'title': '手动安全验证指南',
        'identifier': identifier,
        'verify_url': verify_url,
        'host': parsed_url.netloc,
        'steps': ['打开验证链接', '选择验证方式', '完成验证后回到程序继续确认'],
        'tips': ['验证码有效期通常较短', '收不到验证码时稍后重试'],
    }


__all__ = [
    'VerifyService',
    'manual_verification_guide',
    'VERIFY_REQUIRED',
    'VERIFY_PENDING',
    'VERIFY_MANUAL_ONLY',
    'VERIFY_RESOLVED',
    '_normalize_login_1351',
]
