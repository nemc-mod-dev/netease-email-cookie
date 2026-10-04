#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import time


class StorageService:
    def __init__(self, base_dir='.', artifact_dir='artifacts'):
        self.base_dir = base_dir
        self.artifact_dir = artifact_dir
        os.makedirs(self._artifact_path(''), exist_ok=True)

    def _artifact_path(self, filename):
        return os.path.join(self.base_dir, self.artifact_dir, filename)

    def _safe_label(self, label):
        label = (label or 'account').strip()
        label = label.replace('@', '_at_')
        safe = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in label)
        return safe.strip('_') or 'account'

    def _artifact_filename(self, prefix, label, ext='json'):
        safe_label = self._safe_label(label)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        return f"{prefix}_{safe_label}_{timestamp}.{ext}"

    def _save_artifact_json(self, filename, data):
        path = self._artifact_path(filename)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {'status': 'success', 'path': path}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'path': path}

    def _save_current_artifact_json(self, filename, data):
        path = self._artifact_path(filename)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {'status': 'success', 'path': path}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'path': path}

    def load_artifact_json(self, filename, default=None):
        if default is None:
            default = {}
        try:
            with open(self._artifact_path(filename), 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception:
            return default

    def _load_first_available(self, candidates, default=None):
        if default is None:
            default = {}
        for path in candidates:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return default

    def _load_first_available_raw(self, candidates):
        for path in candidates:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return ''

    def load_current_sauth_payload(self):
        candidates = [self._artifact_path('current_sauth.json'), self._path('sauth_data.json')]
        raw = self._load_first_available(candidates, {})
        sauth_json = raw.get('sauth_json') if isinstance(raw, dict) else None
        return json.loads(sauth_json) if sauth_json else {}

    def load_current_http_cookies(self):
        return self._load_first_available([self._artifact_path('current_http_cookies.json'), self._path('cookies.json')], {})

    def load_current_device_info(self):
        return self._load_first_available([self._artifact_path('current_device_info.json'), self._path('device_info.json')], None)

    def save_current_http_cookies(self, cookies):
        return self._save_current_artifact_json('current_http_cookies.json', cookies)

    def save_current_device_info(self, data):
        return self._save_current_artifact_json('current_device_info.json', data)

    def save_current_sauth_payload(self, payload):
        return self._save_current_artifact_json('current_sauth.json', payload)

    def export_sauth_data(self, sauth_data, label):
        filename = self._artifact_filename('sauth', label)
        payload = {'sauth_json': json.dumps(sauth_data, ensure_ascii=False, separators=(',', ':'))}
        result = self._save_artifact_json(filename, payload)
        result['message'] = 'SAuth 数据已导出' if result['status'] == 'success' else '导出 SAuth 数据失败'
        return result

    def export_http_cookies(self, cookies, label):
        filename = self._artifact_filename('http_cookies', label)
        result = self._save_artifact_json(filename, cookies)
        result['message'] = 'HTTP Cookies 已导出' if result['status'] == 'success' else '导出 HTTP Cookies 失败'
        result['count'] = len(cookies)
        return result

    def export_cookie_format(self, sauth_data, label):
        filename = self._artifact_filename('cookie', label)
        payload = {'sauth_json': json.dumps(sauth_data, ensure_ascii=False, separators=(',', ':'))}
        result = self._save_artifact_json(filename, payload)
        result['message'] = 'Cookie 格式文件已导出' if result['status'] == 'success' else '导出 Cookie 格式失败'
        if result['status'] == 'success':
            result['nemc'] = self.save_nemc_cookie_format(sauth_data, label)
        return result

    def save_current_artifacts(self, sauth_data, cookies, label):
        sauth_payload = {'sauth_json': json.dumps(sauth_data, ensure_ascii=False, separators=(',', ':'))}
        return {
            'current_sauth': self.save_current_sauth_payload(sauth_payload),
            'current_http_cookies': self.save_current_http_cookies(cookies),
            'export_sauth': self.export_sauth_data(sauth_data, label),
            'export_cookie': self.export_cookie_format(sauth_data, label),
            'export_http_cookies': self.export_http_cookies(cookies, label),
        }

    def restore_session_snapshot(self):
        device = self.load_current_device_info() or {}
        sauth = self.load_current_sauth_payload()
        cookies = self.load_current_http_cookies()
        return {
            'device': device,
            'sauth': sauth,
            'cookies': cookies,
            'has_device': bool(device.get('device_id')),
            'has_sauth': bool(sauth.get('sessionid') and sauth.get('sdkuid')),
            'has_cookies': bool(cookies),
        }

    def export_from_restored_session(self, label='restored_session'):
        snapshot = self.restore_session_snapshot()
        if not snapshot.get('has_sauth'):
            return {'status': 'failed', 'message': '当前没有可导出的已恢复会话'}
        artifacts = self.save_current_artifacts(snapshot['sauth'], snapshot['cookies'], label)
        return {'status': 'success', 'message': '已恢复会话已重新导出', 'artifacts': artifacts}

    def clear_legacy_root_exports_note(self):
        return {'status': 'success', 'message': f'新的导出产物统一写入 {self._artifact_path("")}' }

    def _path(self, filename):
        return os.path.join(self.base_dir, filename)

    def load_json(self, filename, default=None):
        if default is None:
            default = {}
        try:
            with open(self._path(filename), 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception:
            return default

    def save_json(self, filename, data):
        path = self._path(filename)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {'status': 'success', 'path': path}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'path': path}

    def load_device_info(self, filename='device_info.json'):
        return self.load_current_device_info()

    def save_device_info(self, device_id, device_key, udid, unique_id, filename='device_info.json'):
        data = {
            'device_id': device_id,
            'device_key': device_key or '',
            'udid': udid,
            'unique_id': unique_id,
            'saved_time': int(time.time()),
        }
        result = self.save_current_device_info(data)
        result['data'] = data
        result['message'] = '设备信息已保存' if result['status'] == 'success' else '保存设备信息失败'
        return result

    def load_sauth_data(self, filename='sauth_data.json'):
        return self.load_current_sauth_payload()

    def save_sauth_data(self, sauth_data, filename='sauth_data.json'):
        payload = {'sauth_json': json.dumps(sauth_data, ensure_ascii=False, separators=(',', ':'))}
        result = self.save_current_sauth_payload(payload)
        result['message'] = '当前 SAuth 状态已保存' if result['status'] == 'success' else '保存当前 SAuth 状态失败'
        return result

    def save_cookie_format(self, sauth_data, label, filename='cookies.json'):
        return self.export_cookie_format(sauth_data, label)

    def save_nemc_cookie_format(self, sauth_data, label, filename=None):
        required_fields = ['sdkuid', 'sessionid', 'deviceid', 'udid']
        missing_fields = [field for field in required_fields if not sauth_data.get(field)]
        if missing_fields:
            return {'status': 'failed', 'message': 'SAuth 缺少必要字段', 'missing_fields': missing_fields}
        try:
            if filename is None:
                filename = self._artifact_filename('nemc_cookie', label)
            payload = {'sauth_json': json.dumps(sauth_data, ensure_ascii=False, separators=(',', ':'))}
            path = self._artifact_path(filename)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            return {'status': 'success', 'message': 'NEMC Cookie 已保存', 'path': path}
        except Exception as e:
            return {'status': 'error', 'message': '保存 NEMC Cookie 失败', 'error': str(e)}
