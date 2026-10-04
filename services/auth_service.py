#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import hashlib
import json
import random
import re
import string
import time
import uuid
from urllib.parse import parse_qs, quote, urlparse

import requests

from services.storage_service import StorageService
from services.verify_service import VerifyService, _normalize_login_1351


class NetEaseAuthService:
    def __init__(self, use_dynamic_device_id=False, storage=None):
        self.session = requests.Session()
        self.storage = storage or StorageService('.')
        self.device_id = None
        self.device_key = None
        self.udid = None
        self.transid = ''
        self.mcount_transaction_id = ''
        self.last_login_context = {}
        self.last_verify_context = {}
        self.last_artifacts = {}
        self.last_mailbox = None
        self.last_error = None

        saved_device = self.storage.load_device_info()
        self.device_info = self._generate_device_info(use_dynamic_device_id)
        if saved_device:
            self.device_id = saved_device.get('device_id')
            self.device_key = saved_device.get('device_key')
            self.udid = saved_device.get('udid', self.udid)
            self.device_info['device_id'] = self.device_id
            self.device_info['unique_id'] = saved_device.get('unique_id', self.device_info['unique_id'])

        self.sauth_data = self.storage.load_sauth_data()
        cookies = self.storage.load_current_http_cookies()
        if cookies:
            self.session.cookies.update(cookies)
        self.current_conversion_complete = False
        self.current_conversion_label = ''
        self.restored_session_exported = False
        self.last_export_paths = []

        restored = self.storage.restore_session_snapshot()
        if restored.get('has_sauth'):
            self.current_conversion_label = 'restored_session'
            self.restored_session_exported = True
        else:
            self.current_conversion_label = ''
            self.restored_session_exported = False

        self.last_export_paths = self._collect_export_paths(self.last_artifacts)


        self.verify_service = VerifyService(
            self.session,
            device_payload_getter=self._verification_payload,
            headers_getter=self._verification_headers,
        )

    def _result(self, status, message='', **kwargs):
        payload = {'status': status, 'message': message}
        payload.update(kwargs)
        return payload

    def _random_hex(self, length):
        return ''.join(random.choice('0123456789abcdef') for _ in range(length))

    def _random_alnum(self, length=32):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

    def _random_step(self):
        return str(random.randint(10**14, 10**15 - 1))

    def _make_aim_info(self):
        return json.dumps({
            'aim': '127.0.0.1', 'country': 'CN', 'tz': '+0800', 'tzid': 'Asia/Shanghai',
            'celluar_ip': '', 'operator': '46015', 'is_vpn_enabled': False,
        }, ensure_ascii=False, separators=(',', ':'))

    def _refresh_transactions(self):
        device_info = getattr(self, 'device_info', {}) or {}
        token = device_info.get('udid') or self.udid or self._random_hex(16)
        timestamp = int(time.time() * 1000)
        self.transid = f"{token}_{timestamp}_{random.randint(10000000, 99999999)}"
        self.mcount_transaction_id = f"{token}_{timestamp}_{random.randint(10000000, 99999999)}"

    def _verification_payload(self):
        return {'cv': self.device_info['cv'], 'gv': self.device_info['gv'], 'app_mode': self.device_info['app_mode'], 'app_channel': self.device_info['app_channel']}

    def _verification_headers(self):
        return {
            'Host': 'service.mkey.163.com', 'Connection': 'keep-alive', 'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest', 'User-Agent': self._get_headers()['User-agent'],
            'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://service.mkey.163.com',
            'Accept-Encoding': 'gzip, deflate', 'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        }

    def _generate_device_info(self, use_dynamic_device_id=False):
        device_id = f"{''.join(random.choices(string.ascii_lowercase, k=16))}-d" if use_dynamic_device_id else 'amawskiaaxanhk66-d'
        self.udid = self._random_hex(16)
        self._refresh_transactions()
        ext_ci = hashlib.sha256(f"{self.udid}{device_id}aecfrxodyqaaaajp-g-x19".encode()).hexdigest()
        unique_id = f"{uuid.uuid4()}{int(time.time() * 1000)}"
        urs_udid = self._random_hex(40)
        info = {
            'device_id': device_id, 'version': '840287970', 'mac': self._random_hex(32), 'urs_udid': urs_udid,
            'unique_id': unique_id, 'brand': 'Redmi', 'device_name': '22081212C', 'device_type': 'mobile',
            'device_model': '22081212C', 'resolution': '1220*2624', 'system_name': 'Android', 'system_version': '13',
            'udid': self.udid, 'app_channel': 'netease', 'pkg_channel': 'netease', 'jf_game_id': 'x19', 'ext_ci': ext_ci,
            'ci_code': '3', 'game_id': 'aecfrxodyqaaaajp-g-x19', 'gv': '840287970', 'gvn': '3.7.15.287970',
            'cv': 'a5.16.0', 'sv': '33', 'app_type': 'games', 'app_mode': '2',
            'mcount_app_key': 'EEkEEXLymcNjM42yLY3Bn6AO15aGy4yq', '_cloud_extra_base64': 'e30=', 'sc': '1',
        }
        self.device_id = info['device_id']
        self.udid = info['udid']
        self._refresh_transactions()
        return info

    def _get_headers(self):
        return {
            'Accept-Charset': 'UTF-8', 'Content-type': 'application/x-www-form-urlencoded', 'Accept-Language': 'zh-cn',
            'User-agent': f"com.netease.x19/{self.device_info['gv']} NeteaseMobileGame/{self.device_info['cv']} ({self.device_info['device_model']};{self.device_info['sv']})",
            'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip',
        }

    def _app_payload(self):
        return {
            'app_channel': self.device_info['app_channel'], 'app_mode': self.device_info['app_mode'], 'app_type': self.device_info['app_type'],
            'cv': self.device_info['cv'], 'ext_ci': self.device_info['ext_ci'], 'game_id': self.device_info['game_id'],
            'gv': self.device_info['gv'], 'gvn': self.device_info['gvn'], 'jf_game_id': self.device_info['jf_game_id'],
            'mcount_app_key': self.device_info['mcount_app_key'], 'mcount_transaction_id': self.mcount_transaction_id,
            'pkg_channel': self.device_info['pkg_channel'], 'sc': self.device_info['sc'], 'sv': self.device_info['sv'],
            'transid': self.transid, '_cloud_extra_base64': self.device_info['_cloud_extra_base64'],
        }

    def _device_payload(self):
        return {
            'urs_udid': self.device_info['urs_udid'], 'init_urs_device': '0', 'unique_id': self.device_info['unique_id'],
            'brand': self.device_info['brand'], 'device_name': self.device_info['device_name'], 'device_type': self.device_info['device_type'],
            'device_model': self.device_info['device_model'], 'resolution': self.device_info['resolution'],
            'system_name': self.device_info['system_name'], 'system_version': self.device_info['system_version'], 'udid': self.device_info['udid'],
        }

    def password_strength(self, password):
        if not password:
            return 0
        length = len(password)
        if length < 6:
            return 1
        is_all_letters = bool(re.match(r'^[a-z]+$', password, re.I))
        is_all_digits = password.isdigit()
        is_all_non_alnum = bool(re.match(r'^[^0-9a-z]+$', password, re.I))
        has_letter = bool(re.search(r'[a-z]', password, re.I))
        has_non_letter = bool(re.search(r'[^a-z]', password, re.I))
        has_digit = bool(re.search(r'\d', password))
        has_non_digit = bool(re.search(r'\D', password))
        has_mixed = (has_letter and has_non_letter) or (has_digit and has_non_digit)
        if is_all_digits or is_all_non_alnum:
            return 1
        if is_all_letters:
            return 1 if length < 8 else 2
        if length < 8:
            return 2 if has_mixed else 1
        return 3 if has_mixed else 2

    def calculate_params(self, device_key=None, username=None, password_md5=None):
        device_key = device_key or self.device_key
        if not device_key:
            return hashlib.md5(f"{self.udid}{self.device_id}{self.device_info['game_id']}{self.device_info['gv']}".encode()).hexdigest()
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            if len(device_key) == 32:
                key_bytes = bytes.fromhex(device_key)
            elif len(device_key) == 64:
                key_bytes = bytes.fromhex(device_key)[:16]
            else:
                key_bytes = device_key.encode()[:16] if isinstance(device_key, str) else device_key[:16]
            payload = {}
            if username and password_md5:
                payload = {'username': username, 'password': password_md5.lower(), 'password_level': self.password_strength(password_md5.lower()), 'unique_id': self.device_info.get('unique_id', '')}
            plaintext = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_ECB)
            return cipher.encrypt(pad(plaintext, AES.block_size)).hex()
        except Exception:
            return hashlib.md5(f"{self.udid}{self.device_id}{self.device_info['game_id']}{self.device_info['gv']}".encode()).hexdigest()

    def generate_device_key(self):
        self._refresh_transactions()
        self.device_info['mac'] = self._random_hex(32)
        self.device_info['ext_ci'] = hashlib.sha256(f"{self.device_info['udid']}{self.device_info['device_id']}{self.device_info['game_id']}".encode()).hexdigest()
        self.device_info['unique_id'] = f"{uuid.uuid4()}{int(time.time() * 1000)}"
        url = f"https://service.mkey.163.com/mpay/games/{self.device_info['game_id']}/devices"
        data = {**self._device_payload(), **self._app_payload(), 'mac': self.device_info['mac']}
        try:
            response = self.session.post(url, data=data, headers=self._get_headers(), timeout=30)
            result = response.json()
            if response.status_code == 201 and 'device' in result and result['device'].get('key'):
                self.device_key = result['device']['key']
                self.device_id = result['device'].get('id', self.device_info['device_id'])
                self.device_info['device_id'] = self.device_id
                save_result = self.storage.save_device_info(self.device_id, self.device_key, self.udid, self.device_info.get('unique_id', ''))
                return self._result('success', '设备创建成功', device=result['device'], save_result=save_result)
            return self._result('failed', '设备创建失败', response_code=response.status_code, error=result)
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '设备创建异常', error=str(e))

    def upload_device_details(self):
        self._refresh_transactions()
        url = 'https://service.mkey.163.com/mpay/api/devices/upload'
        data = {'device_id': self.device_info['device_id'], 'version': self.device_info['version'], 'mac': self.device_info['mac'], **self._device_payload(), **self._app_payload(), 'ci_code': self.device_info['ci_code']}
        try:
            response = self.session.post(url, data=data, headers=self._get_headers(), timeout=30)
            result = response.json()
            if result.get('upload_time') is not None:
                return self._result('success', '设备信息上传成功', data=result)
            return self._result('failed', '设备信息上传失败', error=result)
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '设备信息上传异常', error=str(e))

    def prepare_device(self):
        steps = []
        if self.device_key:
            steps.append({'step': 'reuse_device', 'device_id': self.device_id})
            upload = self.upload_device_details()
            steps.append(upload)
            return self._result(upload['status'], upload['message'], steps=steps, device_id=self.device_id)
        create = self.generate_device_key()
        steps.append(create)
        if create['status'] != 'success':
            return self._result(create['status'], create['message'], steps=steps)
        upload = self.upload_device_details()
        steps.append(upload)
        return self._result(upload['status'], upload['message'], steps=steps, device_id=self.device_id)

    def rebuild_device(self):
        self.device_key = None
        self.device_info = self._generate_device_info(True)
        return self.prepare_device()

    def _build_sauth(self, user_data):
        return {
            'access_token': user_data.get('ext_access_token', '') or '', 'aim_info': self._make_aim_info(), 'app_channel': 'netease',
            'client_login_sn': self._random_alnum(32), 'deviceid': self.device_info['device_id'], 'gameid': 'x19',
            'get_access_token': '1', 'ip': '127.0.0.1', 'is_unisdk_guest': 0, 'login_channel': 'netease', 'platform': 'ad',
            'sdk_version': '5.16.0', 'sdkuid': user_data.get('id', ''), 'sessionid': user_data.get('token', ''),
            'source_app_channel': 'netease', 'source_platform': 'ad', 'step': self._random_step(), 'step2': self._random_step(),
            'udid': user_data.get('udid') or self.udid,
        }

    def _collect_export_paths(self, artifacts):
        paths = []
        if not isinstance(artifacts, dict):
            return paths
        for result in artifacts.values():
            if isinstance(result, dict):
                if result.get('path'):
                    paths.append(result['path'])
                nested = result.get('nemc')
                if isinstance(nested, dict) and nested.get('path'):
                    paths.append(nested['path'])
        return paths

    def save_cookies(self, filename='cookies.json'):
        cookies = self.session.cookies.get_dict()
        result = self.storage.save_current_http_cookies(cookies)
        result['message'] = '当前 HTTP Cookies 状态已保存' if result['status'] == 'success' else '保存当前 HTTP Cookies 状态失败'
        result['count'] = len(cookies)
        return result

    def _finalize_auth_state(self, user_data, label):
        self.sauth_data = self._build_sauth(user_data)
        cookies = self.session.cookies.get_dict()
        self.storage.save_sauth_data(self.sauth_data)
        self.storage.save_current_http_cookies(cookies)
        self.current_conversion_complete = True
        self.current_conversion_label = label
        self.restored_session_exported = False
        self.last_artifacts = self.storage.save_current_artifacts(self.sauth_data, cookies, label)
        self.last_export_paths = self._collect_export_paths(self.last_artifacts)
        return self.last_artifacts

    def login_email(self, email, password, retry_count=0):
        self.last_login_context = {'mode': 'email', 'identifier': email}
        encoded = quote(base64.b64encode(email.encode('utf-8')).decode('utf-8'))
        url = f"https://service.mkey.163.com/mpay/{self.device_info['app_type']}/{self.device_info['game_id']}/devices/{self.device_info['device_id']}/users?un={encoded}"
        password_md5 = hashlib.md5(password.encode('utf-8')).hexdigest()
        self._refresh_transactions()
        data = {'opt_fields': 'nickname,avatar,realname_status,mobile_bind_status,exit_popup_info,mask_related_mobile,related_login_status,detect_is_new_user', 'params': self.calculate_params(username=email, password_md5=password_md5), **self._app_payload()}
        try:
            result = self.session.post(url, data=data, headers=self._get_headers(), timeout=30).json()
            if result.get('userid') or result.get('user'):
                artifacts = self._finalize_auth_state(result.get('user', {}), email)
                return self._result('success', '登录成功', login_mode='email', user_info=result, sauth_data=self.sauth_data, artifacts=artifacts)
            if result.get('code') == 1351:
                verify_url = result.get('verify_url') or result.get('verify')
                verify_info = self.verify_service.handle_verification(verify_url, email)
                self.last_verify_context = verify_info
                return _normalize_login_1351(result, verify_info)
            if result.get('code') == 1311 and retry_count < 1:
                rebuilt = self.rebuild_device()
                if rebuilt['status'] == 'success':
                    retry = self.login_email(email, password, retry_count + 1)
                    retry['auto_rebuilt_device'] = True
                    return retry
                return self._result('failed', '设备重建后仍无法登录', error=result, rebuild_result=rebuilt)
            return self._result('failed', result.get('reason', '登录失败'), error=result, error_code=result.get('code'), error_reason=result.get('reason', '登录失败'))
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '邮箱登录异常', error=str(e))

    def request_phone_login_sms(self, phone_number):
        self.last_login_context = {'mode': 'phone', 'identifier': phone_number}
        self._refresh_transactions()
        url = 'https://service.mkey.163.com/mpay/api/users/login/mobile/get_sms'
        data = {**self._app_payload(), 'device_id': self.device_info['device_id'], 'mobile': phone_number, 'urs_udid': self.device_info['urs_udid']}
        try:
            result = self.session.post(url, data=data, headers=self._get_headers(), timeout=30).json()
            if result.get('reply_sms') or result.get('code') in (0, 200, 201):
                return self._result('success', result.get('reason', '短信验证码已请求'), phone_number=phone_number, data=result)
            return self._result('failed', result.get('reason', '请求短信验证码失败'), error=result)
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '请求短信验证码异常', error=str(e))

    def verify_phone_login_sms(self, phone_number, verify_code):
        self._refresh_transactions()
        url = 'https://service.mkey.163.com/mpay/api/users/login/mobile/verify_sms'
        data = {**self._app_payload(), 'device_id': self.device_info['device_id'], 'mobile': phone_number, 'login_for': '1', 'smscode': verify_code, 'up_content': '', 'urs_udid': self.device_info['urs_udid']}
        try:
            result = self.session.post(url, data=data, headers=self._get_headers(), timeout=30).json()
            if result.get('ticket'):
                return self._result('success', result.get('reason', '短信验证码校验成功'), ticket=result.get('ticket'), related_emails=result.get('related_emails', []), related_accounts=result.get('related_accounts', []), data=result)
            return self._result('failed', result.get('reason', '短信验证码校验失败'), error=result)
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '短信验证码校验异常', error=str(e))

    def login_phone_with_ticket(self, phone_number, ticket):
        self.last_login_context = {'mode': 'phone', 'identifier': phone_number, 'ticket': ticket}
        self._refresh_transactions()
        url = 'https://service.mkey.163.com/mpay/api/users/login/mobile/finish'
        params = {'un': quote(base64.b64encode(phone_number.encode('utf-8')).decode('utf-8'))}
        data = {**self._app_payload(), 'device_id': self.device_info['device_id'], 'login_for': '1', 'ticket': ticket, 'urs_udid': self.device_info['urs_udid'], 'opt_fields': 'nickname,avatar,realname_status,mobile_bind_status,exit_popup_info,mask_related_mobile,related_login_status,detect_is_new_user'}
        try:
            result = self.session.post(url, data=data, params=params, headers=self._get_headers(), timeout=30).json()
            if result.get('user'):
                artifacts = self._finalize_auth_state(result.get('user', {}), phone_number)
                return self._result('success', '手机号登录成功', login_mode='phone', user_info=result, sauth_data=self.sauth_data, artifacts=artifacts)
            return self._result('failed', result.get('reason', '手机号登录失败'), error=result)
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '手机号登录异常', error=str(e))

    def login_phone(self, phone_number, verify_code):
        verify_result = self.verify_phone_login_sms(phone_number, verify_code)
        if verify_result['status'] != 'success':
            return verify_result
        return self.login_phone_with_ticket(phone_number, verify_result['ticket'])

    def verify_with_ticket(self, ticket, label=None):
        result = self.verify_service.submit_verification_result(ticket)
        if result['status'] == 'success':
            label = label or self.last_login_context.get('identifier') or 'verified_account'
            artifacts = self._finalize_auth_state(result.get('user_info', {}), label)
            return self._result('success', '验证确认成功', ticket=ticket, user_info=result.get('user_info', {}), sauth_data=self.sauth_data, artifacts=artifacts)
        return result

    def send_verify_sms(self, ticket):
        return self.verify_service.send_sms_code(ticket)

    def check_verification_status(self, ticket):
        return self.verify_service.check_verification_status(ticket)

    def get_mailbox_list(self):
        if not self.sauth_data.get('sessionid'):
            return self._result('failed', '未找到有效的 sessionid')
        self._refresh_transactions()
        url = 'https://mailbox.g.mkey.163.com/mpay/api/mailbox/fetch_list'
        params = {'game_id': self.device_info['game_id'], 'user_id': self.sauth_data.get('sdkuid'), 'device_id': self.device_info['device_id'], 'token': self.sauth_data.get('sessionid'), 'fetch_type': '0', **self._app_payload()}
        try:
            result = self.session.get(url, params=params, headers=self._get_headers(), timeout=30).json()
            self.last_mailbox = result
            return self._result('success', '邮箱列表获取成功', mailbox=result)
        except Exception as e:
            self.last_error = str(e)
            return self._result('error', '获取邮箱列表异常', error=str(e))

    def load_cookies(self, filename='cookies.json'):
        try:
            cookies = self.storage.load_current_http_cookies()
            self.session.cookies.update(cookies)
            return self._result('success', 'HTTP Cookies 已加载', path=self.storage._artifact_path('current_http_cookies.json'), count=len(cookies))
        except Exception as e:
            return self._result('error', '加载 HTTP Cookies 失败', error=str(e), path=filename)

    def save_all_artifacts(self, label):
        if not self.current_conversion_complete:
            return self._result('failed', '当前没有新的转换结果可导出，请先完成本次转换')
        cookies = self.session.cookies.get_dict()
        self.last_artifacts = self.storage.save_current_artifacts(self.sauth_data, cookies, label)
        self.last_export_paths = self._collect_export_paths(self.last_artifacts)
        return self._result('success', '认证产物已导出到专用目录', artifacts=self.last_artifacts, export_paths=self.last_export_paths)

    def export_restored_session(self, label='restored_session'):
        result = self.storage.export_from_restored_session(label)
        if result.get('status') == 'success':
            self.restored_session_exported = True
            self.last_artifacts = result.get('artifacts', {})
            self.last_export_paths = self._collect_export_paths(self.last_artifacts)
            return self._result('success', '已恢复会话已重新导出到专用目录', artifacts=self.last_artifacts, export_paths=self.last_export_paths)
        return self._result(result.get('status', 'failed'), result.get('message', '导出已恢复会话失败'))

    def extract_verify_info_from_url(self, verify_url):
        parsed = self.verify_service.parse_verify_url(verify_url)
        return parsed.get('ticket', ''), parsed.get('code', '')

    def extract_ticket_from_url(self, verify_url):
        try:
            return parse_qs(urlparse(verify_url).query).get('ticket', [''])[0]
        except Exception:
            return None

    def get_state_snapshot(self):
        restored = self.storage.restore_session_snapshot()
        return {
            'device_id': self.device_info.get('device_id'), 'device_key_present': bool(self.device_key), 'unique_id': self.device_info.get('unique_id'),
            'udid': self.device_info.get('udid'), 'sdkuid': self.sauth_data.get('sdkuid'), 'sessionid_present': bool(self.sauth_data.get('sessionid')),
            'last_login_context': self.last_login_context, 'last_verify_context': self.last_verify_context, 'last_artifacts': self.last_artifacts,
            'cookie_count': len(self.session.cookies.get_dict()), 'restored_session': restored,
            'current_conversion_complete': self.current_conversion_complete,
            'current_conversion_label': self.current_conversion_label,
            'restored_session_exported': self.restored_session_exported,
            'export_paths': self.last_export_paths,
        }
