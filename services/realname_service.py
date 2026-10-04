#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网易 mkey 实名认证接口封装。

接口与参数来自抓包 ``dispatch-api-online.vemarsdev.com_2026_10_04_15_54_17.har``。

审查（判断账号是否需要实名）::

    GET https://service.mkey.163.com/mpay/games/{game_id}/devices/{device_id}/users/{user_id}/info
        ?token={sessionid}&opt_fields=realname_status&<app_payload>

    返回示例::

        {"user": {"realname_status": 0, "need_aas": true, "refill_realname_flag": 0, ...}}

提交实名（抓包中 verify 之后紧跟一次 update_by_token，参数完全一致）::

    POST https://service.mkey.163.com/mpay/api/users/realname/verify
         form: device_id,user_id,token,realname,id_region,id_num,<app_payload>
    POST https://service.mkey.163.com/mpay/api/users/realname/update_by_token

    返回示例::

        {"need_aas": false, "realname_type": "成年人"}

状态取值说明：抓包中未实名账号为 ``realname_status == 0``。``1`` 按“已实名”处理；
其余（含字段缺失/非预期值）统一视为 ``unknown``，**不会自动提交**，需人工确认。
"""

import re

REALNAME_VERIFIED = 'verified'
REALNAME_REQUIRED = 'required'
REALNAME_UNKNOWN = 'unknown'

# 抓包只覆盖了 realname_status == 0（未实名）。1 视为已实名；如有新样本请在此扩展。
_VERIFIED_STATUS_VALUES = frozenset({1})

_ID_NUM_18 = re.compile(r'^\d{17}[\dXx]$')
_ID_NUM_15 = re.compile(r'^\d{15}$')


def mask_realname(name):
    name = (name or '').strip()
    if len(name) <= 1:
        return name or ''
    if len(name) == 2:
        return name[0] + '*'
    return name[0] + '*' * (len(name) - 2) + name[-1]


def mask_id_num(id_num):
    id_num = (id_num or '').strip()
    if len(id_num) <= 6:
        return '*' * len(id_num)
    return id_num[:3] + '*' * (len(id_num) - 7) + id_num[-4:]


def validate_id_num(id_num):
    """基本格式校验：18 位（含校验位）或 15 位。返回 (是否合法, 说明)。"""
    value = (id_num or '').strip().upper()
    if _ID_NUM_15.match(value):
        return True, ''
    if not _ID_NUM_18.match(value):
        return False, '身份证号应为 15 位或 18 位'
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    checks = '10X98765432'
    total = sum(int(value[i]) * weights[i] for i in range(17))
    if checks[total % 11] != value[17]:
        return False, '身份证号校验位不正确'
    return True, ''


def classify_realname(user):
    """根据用户信息推断实名状态，返回 (state, detail)。"""
    if not isinstance(user, dict):
        return REALNAME_UNKNOWN, {}
    status = user.get('realname_status')
    detail = {
        'realname_status': status,
        'need_aas': user.get('need_aas'),
        'refill_realname_flag': user.get('refill_realname_flag'),
        'is_channel_adult': user.get('is_channel_adult'),
    }
    if status in _VERIFIED_STATUS_VALUES:
        return REALNAME_VERIFIED, detail
    if status == 0:
        return REALNAME_REQUIRED, detail
    return REALNAME_UNKNOWN, detail


def _result(status, message, **kwargs):
    payload = {'status': status, 'message': message}
    payload.update(kwargs)
    return payload


def _as_json(response):
    content_type = (response.headers or {}).get('content-type', '')
    text = getattr(response, 'text', '') or ''
    try:
        return response.json(), None
    except Exception as e:  # json.JSONDecodeError 及自定义 json() 抛错
        diagnostic = {
            'status_code': getattr(response, 'status_code', None),
            'content_type': content_type,
            'text_preview': text[:200],
        }
        return None, _result('error', '响应不是合法 JSON', error=str(e), diagnostic=diagnostic)


class RealnameService:
    """封装实名审查与提交；session / app_payload / 设备信息由外部提供。"""

    def __init__(self, session, app_payload_getter, headers_getter, device_info_getter):
        self.session = session
        self._app_payload = app_payload_getter
        self._headers = headers_getter
        self._device_info = device_info_getter

    def _device_id(self, device_id=None):
        if device_id:
            return device_id
        return (self._device_info() or {}).get('device_id', '')

    def _game_id(self):
        return (self._device_info() or {}).get('game_id', '')

    def _info_url(self, user_id, device_id=None):
        return (
            f"https://service.mkey.163.com/mpay/games/{self._game_id()}"
            f"/devices/{self._device_id(device_id)}/users/{user_id}/info"
        )

    def query_status(self, user_id, token, device_id=None):
        """审查账号实名状态。返回 status/message/realname_state/needs_realname 等。"""
        if not user_id or not token:
            return _result('failed', '缺少 user_id 或 token', realname_state=REALNAME_UNKNOWN, needs_realname=False)
        params = {**self._app_payload(), 'token': token, 'opt_fields': 'realname_status'}
        try:
            response = self.session.get(self._info_url(user_id, device_id), params=params, headers=self._headers(), timeout=30)
        except Exception as e:
            return _result('error', '查询实名状态异常', error=str(e), realname_state=REALNAME_UNKNOWN, needs_realname=False)

        data, error = _as_json(response)
        if error is not None:
            error.setdefault('realname_state', REALNAME_UNKNOWN)
            error.setdefault('needs_realname', False)
            return error
        user = data.get('user') if isinstance(data, dict) else None
        if not isinstance(user, dict):
            return _result('failed', '查询实名状态失败', error=data, realname_state=REALNAME_UNKNOWN, needs_realname=False)
        state, detail = classify_realname(user)
        return _result(
            'success', '实名状态查询成功',
            realname_state=state, needs_realname=(state == REALNAME_REQUIRED), **detail,
        )

    def _submit_once(self, endpoint, user_id, token, realname, id_num, id_region, device_id):
        url = f"https://service.mkey.163.com/mpay/api/users/realname/{endpoint}"
        data = {
            **self._app_payload(),
            'device_id': self._device_id(device_id),
            'user_id': user_id,
            'token': token,
            'realname': realname,
            'id_region': id_region,
            'id_num': id_num,
        }
        try:
            response = self.session.post(url, data=data, headers=self._headers(), timeout=30)
        except Exception as e:
            return _result('error', f'{endpoint} 请求异常', error=str(e), endpoint=endpoint)
        payload, error = _as_json(response)
        if error is not None:
            error['endpoint'] = endpoint
            return error
        code = payload.get('code') if isinstance(payload, dict) else None
        ok = isinstance(payload, dict) and code in (None, 0, 200)
        if ok:
            return _result(
                'success', '实名提交成功', endpoint=endpoint, data=payload,
                need_aas=payload.get('need_aas'), realname_type=payload.get('realname_type'),
            )
        reason = payload.get('reason') if isinstance(payload, dict) else None
        return _result('failed', reason or '实名提交失败', endpoint=endpoint, error=payload, error_code=code)

    def submit(self, user_id, token, realname, id_num, id_region='86', device_id=None, sync=True):
        """提交实名。默认按抓包顺序先 verify 再 update_by_token。"""
        realname = (realname or '').strip()
        id_num = (id_num or '').strip().upper()
        if not user_id or not token:
            return _result('failed', '缺少 user_id 或 token')
        if not realname:
            return _result('failed', '缺少实名姓名')
        valid, reason = validate_id_num(id_num)
        if not valid:
            return _result('failed', f'实名信息不合法: {reason}', error=reason)

        verify = self._submit_once('verify', user_id, token, realname, id_num, id_region, device_id)
        if verify['status'] != 'success':
            return verify
        if not sync:
            return verify

        update = self._submit_once('update_by_token', user_id, token, realname, id_num, id_region, device_id)
        result = dict(verify)
        result['sync_status'] = update['status']
        result['sync'] = update
        if update['status'] != 'success':
            result['status'] = 'partial'
            result['message'] = '实名已提交，但 update_by_token 回写失败'
            return result
        result['need_aas'] = update.get('need_aas', verify.get('need_aas'))
        result['realname_type'] = update.get('realname_type', verify.get('realname_type'))
        return result


__all__ = [
    'RealnameService',
    'classify_realname',
    'validate_id_num',
    'mask_realname',
    'mask_id_num',
    'REALNAME_VERIFIED',
    'REALNAME_REQUIRED',
    'REALNAME_UNKNOWN',
]
