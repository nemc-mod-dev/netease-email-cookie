#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量实名认证编排：**先审查是否需要实名，再按需提交**，最后输出报告。

每个账号的处理流程：

1. 准备会话：优先使用账号自带的 ``sauth`` / ``sauth_file``；否则用邮箱+密码
   或手机号+短信验证码登录换取会话。
2. 设备复用：同一批次共享一个设备（首个账号创建，其余复用），减少重复注册。
3. 审查：``GET .../users/{uid}/info?opt_fields=realname_status``
4. 提交（仅当 ``submit=True`` 且确实需要实名且提供了实名信息）：
   ``POST realname/verify`` + ``POST realname/update_by_token``
5. 记录报告：身份信息脱敏，**不落盘完整姓名/证件号**。

账号条目（JSON）字段::

    {
      "identifier": "aa41153216567@163.com",  // 必填（除非用 sauth_file）
      "password": "...",                      // 邮箱模式必填
      "mode": "email",                        // email（默认）| phone
      "sms_code": "123456",                   // phone 模式必填
      "sauth": { ... },                       // 可选：直接提供会话，跳过登录
      "sauth_file": "artifacts/nemc_cookie_xxx.json",  // 可选：从产物读取会话
      "cookies": { ... },                     // 可选：补充 cookies
      "realname": "张三",                     // 可选：实名姓名
      "id_num": "110101199001011234",         // 可选：证件号
      "id_region": "86",                      // 可选，默认 86
      "label": "备注名"                        // 可选
    }
"""

import csv
import json
import os
import time

from services.auth_service import NetEaseAuthService
from services.realname_service import (
    REALNAME_REQUIRED,
    REALNAME_UNKNOWN,
    REALNAME_VERIFIED,
    mask_id_num,
    mask_realname,
)
from services.storage_service import StorageService

FAILED_STAGES = ('device_failed', 'login_failed', 'missing_password', 'need_sms_code', 'review_failed', 'error')

REPORT_COLUMNS = [
    'index', 'label', 'identifier', 'session_source', 'device_id', 'stage',
    'realname_state', 'needs_realname', 'need_aas', 'refill_realname_flag',
    'submit_status', 'submit_message', 'realname_masked', 'id_num_masked',
    'confirmed_state', 'error',
]


def _safe_label(label):
    label = (label or 'account').strip().replace('@', '_at_')
    safe = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in label)
    return safe.strip('_') or 'account'


def load_sauth_from_file(path):
    """从 nemc_cookie / sauth 产物中读取会话。"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and data.get('sauth_json'):
        return json.loads(data['sauth_json'])
    if isinstance(data, dict) and data.get('sessionid'):
        return data
    raise ValueError(f'无法从 {path} 解析会话')


class BatchRealnameRunner:
    def __init__(self, output_root='artifacts/batch', auth_factory=None, sleeper=time.sleep):
        self.output_root = output_root
        self.auth_factory = auth_factory or (lambda storage: NetEaseAuthService(storage=storage))
        self.sleeper = sleeper

    def _new_auth(self, account, run_dir, shared_device):
        label = account.get('label') or account.get('identifier') or 'account'
        account_dir = os.path.join(run_dir, 'accounts', _safe_label(label))
        storage = StorageService(account_dir)

        sauth = account.get('sauth') or None
        if not sauth and account.get('sauth_file'):
            sauth = load_sauth_from_file(account['sauth_file'])

        # 复用已有会话时不覆盖设备；否则用共享设备预置，避免每账号重复注册。
        if shared_device and not sauth:
            storage.save_current_device_info(shared_device)

        return self.auth_factory(storage), sauth, label

    @staticmethod
    def _acquire_session(auth, account, sauth):
        if sauth:
            auth.inject_session(sauth, account.get('cookies'))
            return {'stage': 'session_ready', 'session_source': 'provided'}

        prepare = auth.prepare_device()
        if prepare['status'] != 'success':
            return {'stage': 'device_failed', 'error': prepare.get('message'), 'detail': prepare}

        if account.get('mode') == 'phone':
            code = account.get('sms_code')
            if not code:
                return {'stage': 'need_sms_code', 'error': '手机号模式需要提供 sms_code'}
            login = auth.login_phone(account['identifier'], code)
        else:
            password = account.get('password')
            if not password:
                return {'stage': 'missing_password', 'error': '邮箱模式需要提供 password'}
            login = auth.login_email(account['identifier'], password)

        if login['status'] != 'success':
            return {'stage': 'login_failed', 'error': login.get('message'), 'detail': login}
        return {'stage': 'session_ready', 'session_source': 'login'}

    def process_account(self, account, run_dir, index=0, submit=False, shared_device=None,
                        default_realname='', default_id_num='', default_id_region='86'):
        record = {
            'index': index,
            'label': account.get('label') or account.get('identifier') or 'account',
            'identifier': account.get('identifier', ''),
            'stage': 'init',
            'realname_state': REALNAME_UNKNOWN,
            'needs_realname': None,
            'submit_status': None,
        }
        try:
            auth, sauth, label = self._new_auth(account, run_dir, shared_device)
            record['label'] = label
            record['device_id'] = getattr(auth, 'device_id', None)

            session = self._acquire_session(auth, account, sauth)
            record['session_source'] = session.get('session_source')
            if session['stage'] != 'session_ready':
                record['stage'] = session['stage']
                record['error'] = session.get('error')
                record['detail'] = session.get('detail')
                return record

            record['_device'] = {
                'device_id': auth.device_id,
                'device_key': auth.device_key,
                'udid': auth.udid,
                'unique_id': auth.device_info.get('unique_id'),
            }

            review = auth.check_realname_status()
            if review.get('status') != 'success':
                record['stage'] = 'review_failed'
                record['error'] = review.get('message')
                record['detail'] = review
                return record
            record['realname_state'] = review.get('realname_state', REALNAME_UNKNOWN)
            record['needs_realname'] = bool(review.get('needs_realname'))
            record['need_aas'] = review.get('need_aas')
            record['refill_realname_flag'] = review.get('refill_realname_flag')
            record['stage'] = 'reviewed'

            if not (submit and record['needs_realname']):
                return record

            realname = account.get('realname') or default_realname
            id_num = account.get('id_num') or default_id_num
            id_region = account.get('id_region') or default_id_region
            record['realname_masked'] = mask_realname(realname)
            record['id_num_masked'] = mask_id_num(id_num)
            if not realname or not id_num:
                record['submit_status'] = 'skipped'
                record['error'] = '需要实名但未提供 realname/id_num'
                return record

            result = auth.submit_realname(realname, id_num, id_region=id_region)
            record['submit_status'] = result.get('status')
            record['submit_message'] = result.get('message')
            record['need_aas'] = result.get('need_aas', record.get('need_aas'))
            record['realname_type'] = result.get('realname_type')
            if result.get('status') in ('success', 'partial'):
                confirm = auth.check_realname_status()
                record['confirmed_state'] = confirm.get('realname_state')
                record['stage'] = 'submitted'
            else:
                record['stage'] = 'submit_failed'
                record['detail'] = result
            return record
        except Exception as e:
            record['stage'] = 'error'
            record['error'] = str(e)
            return record

    def run(self, accounts, submit=False, delay=0.0, default_realname='', default_id_num='',
            default_id_region='86', on_progress=None):
        run_id = time.strftime('%Y%m%d_%H%M%S')
        run_dir = os.path.join(self.output_root, run_id)
        os.makedirs(run_dir, exist_ok=True)

        results = []
        shared_device = None
        for i, account in enumerate(accounts, 1):
            record = self.process_account(
                account, run_dir, index=i, submit=submit, shared_device=shared_device,
                default_realname=default_realname, default_id_num=default_id_num,
                default_id_region=default_id_region,
            )
            device = record.pop('_device', None)
            if device and device.get('device_id'):
                shared_device = device
            results.append(record)
            if on_progress:
                on_progress(i, len(accounts), record)
            if delay and i < len(accounts):
                self.sleeper(delay)

        report = self._build_report(run_id, run_dir, results, submit)
        self._write_report(run_dir, report)
        return report

    @staticmethod
    def _build_report(run_id, run_dir, results, submit):
        summary = {'total': len(results), 'verified': 0, 'required': 0, 'unknown': 0,
                   'submitted': 0, 'submit_failed': 0, 'skipped': 0, 'failed': 0}
        for r in results:
            state = r.get('realname_state')
            if state == REALNAME_VERIFIED:
                summary['verified'] += 1
            elif state == REALNAME_REQUIRED:
                summary['required'] += 1
            else:
                summary['unknown'] += 1

            status = r.get('submit_status')
            if status == 'success':
                summary['submitted'] += 1
            elif status in ('failed', 'partial', 'error'):
                summary['submit_failed'] += 1
            elif status == 'skipped':
                summary['skipped'] += 1

            if r.get('stage') in FAILED_STAGES:
                summary['failed'] += 1
        return {
            'run_id': run_id,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'submit_enabled': submit,
            'run_dir': run_dir,
            'summary': summary,
            'results': results,
        }

    @staticmethod
    def _write_report(run_dir, report):
        json_path = os.path.join(run_dir, 'report.json')
        csv_path = os.path.join(run_dir, 'report.csv')
        report['report_json'] = json_path
        report['report_csv'] = csv_path

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, extrasaction='ignore')
            writer.writeheader()
            for r in report['results']:
                writer.writerow(r)


__all__ = ['BatchRealnameRunner', 'load_sauth_from_file']
