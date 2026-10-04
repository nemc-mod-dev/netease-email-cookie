#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量账号编排：转 Cookie 与实名审查/提交。

设计要点：

- **无主账号、无跨运行会话**。每个账号在自己的处理步骤里独立登录。
- 同一批次共享一个设备（首个账号注册，其余复用），减少重复注册。
- 遇到需要人工完成的 1351 安全验证时，**跳过并记录**（ticket + 验证链接），
  不阻塞整批；汇总写到 ``needs_verify.json``。
- 实名提交**只使用账号条目自带的身份信息**，不提供全局默认身份；
  缺失身份的账号会被跳过。
- 报告中的身份信息一律脱敏，不落盘完整姓名/证件号。

账号条目字段（JSON）::

    {
      "identifier": "user@163.com",           // 必填（除非用 sauth_file）
      "password": "...",                       // 邮箱模式必填
      "mode": "email",                         // email（默认）| phone
      "sms_code": "123456",                    // phone 模式必填
      "sauth": { ... },                        // 可选：直接提供会话，跳过登录
      "sauth_file": "artifacts/nemc_cookie_x.json",  // 可选
      "cookies": { ... },                      // 可选
      "realname": "张三",                      // 可选：提交实名时的姓名
      "id_num": "110101199001011234",          // 可选：提交实名时的证件号
      "id_region": "86",                       // 可选，默认 86
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

FAILED_STAGES = (
    'device_failed', 'login_failed', 'missing_password', 'need_sms_code',
    'review_failed', 'submit_failed', 'export_failed', 'error',
)

COOKIE_REPORT_COLUMNS = [
    'index', 'label', 'identifier', 'session_source', 'device_id', 'stage',
    'nemc_path', 'ticket', 'verify_url', 'error',
]

REALNAME_REPORT_COLUMNS = [
    'index', 'label', 'identifier', 'session_source', 'device_id', 'stage',
    'realname_state', 'needs_realname', 'need_aas', 'refill_realname_flag',
    'submit_status', 'submit_message', 'realname_masked', 'id_num_masked',
    'confirmed_state', 'ticket', 'verify_url', 'error',
]


def _safe_label(label):
    label = (label or 'account').strip().replace('@', '_at_')
    safe = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in label)
    return safe.strip('_') or 'account'


def _extract_nemc_path(artifacts):
    if not artifacts:
        return None
    cookie = artifacts.get('export_cookie') or {}
    if not isinstance(cookie, dict):
        return None
    nemc = cookie.get('nemc') or {}
    if isinstance(nemc, dict) and nemc.get('path'):
        return nemc['path']
    return cookie.get('path')


def load_sauth_from_file(path):
    """从 nemc_cookie / sauth 产物中读取会话。"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and data.get('sauth_json'):
        return json.loads(data['sauth_json'])
    if isinstance(data, dict) and data.get('sessionid'):
        return data
    raise ValueError(f'无法从 {path} 解析会话')


class _BatchRunnerBase:
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
        """获取会话。1351 返回 needs_manual_verify 而不是直接失败。"""
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

        if login.get('status') == 'need_verify':
            return {
                'stage': 'needs_manual_verify',
                'error': login.get('message') or '需要人工完成安全验证',
                'ticket': login.get('ticket'),
                'verify_url': login.get('verify_url'),
                'detail': login,
            }
        if login['status'] != 'success':
            return {'stage': 'login_failed', 'error': login.get('message'), 'detail': login}
        return {'stage': 'session_ready', 'session_source': 'login'}

    @staticmethod
    def _device_record(auth):
        return {
            'device_id': auth.device_id,
            'device_key': auth.device_key,
            'udid': auth.udid,
            'unique_id': auth.device_info.get('unique_id'),
        }

    @staticmethod
    def _apply_session_failure(record, session):
        record['stage'] = session['stage']
        record['error'] = session.get('error')
        if session.get('ticket'):
            record['ticket'] = session['ticket']
        if session.get('verify_url'):
            record['verify_url'] = session['verify_url']
        return record

    @staticmethod
    def _collect_manual(results):
        return [
            {'index': r.get('index'), 'identifier': r.get('identifier'),
             'ticket': r.get('ticket'), 'verify_url': r.get('verify_url')}
            for r in results if r.get('stage') == 'needs_manual_verify'
        ]

    def _run_loop(self, accounts, delay, on_progress, process):
        run_id = time.strftime('%Y%m%d_%H%M%S')
        run_dir = os.path.join(self.output_root, run_id)
        os.makedirs(run_dir, exist_ok=True)

        results = []
        shared_device = None
        for i, account in enumerate(accounts, 1):
            record = process(account, run_dir, i, shared_device)
            device = record.pop('_device', None)
            if device and device.get('device_id'):
                shared_device = device
            results.append(record)
            if on_progress:
                on_progress(i, len(accounts), record)
            if delay and i < len(accounts):
                self.sleeper(delay)
        return run_id, run_dir, results

    @staticmethod
    def _write_report(run_dir, report, columns):
        json_path = os.path.join(run_dir, 'report.json')
        csv_path = os.path.join(run_dir, 'report.csv')
        report['report_json'] = json_path
        report['report_csv'] = csv_path

        manual = report.get('needs_manual_verify') or []
        if manual:
            manual_path = os.path.join(run_dir, 'needs_verify.json')
            with open(manual_path, 'w', encoding='utf-8') as f:
                json.dump(manual, f, ensure_ascii=False, indent=2)
            report['needs_verify_json'] = manual_path

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            for r in report['results']:
                writer.writerow(r)


class BatchCookieRunner(_BatchRunnerBase):
    """批量登录并把账号转换成可复用 Cookie 产物。"""

    def process_account(self, account, run_dir, index=0, shared_device=None):
        record = {
            'index': index,
            'label': account.get('label') or account.get('identifier') or 'account',
            'identifier': account.get('identifier', ''),
            'stage': 'init',
        }
        try:
            auth, sauth, label = self._new_auth(account, run_dir, shared_device)
            record['label'] = label

            session = self._acquire_session(auth, account, sauth)
            record['session_source'] = session.get('session_source')
            if session['stage'] != 'session_ready':
                return self._apply_session_failure(record, session)

            record['_device'] = self._device_record(auth)
            record['device_id'] = auth.device_id

            if not getattr(auth, 'last_artifacts', None):
                export = auth.save_all_artifacts(label)
                if export.get('status') != 'success':
                    record['stage'] = 'export_failed'
                    record['error'] = export.get('message')
                    return record

            record['stage'] = 'cookie_ready'
            record['nemc_path'] = _extract_nemc_path(auth.last_artifacts)
            return record
        except Exception as e:
            record['stage'] = 'error'
            record['error'] = str(e)
            return record

    def run(self, accounts, delay=0.0, on_progress=None):
        run_id, run_dir, results = self._run_loop(accounts, delay, on_progress, self.process_account)
        summary = {'total': len(results), 'ready': 0, 'needs_manual_verify': 0, 'failed': 0}
        for r in results:
            if r.get('stage') == 'cookie_ready':
                summary['ready'] += 1
            elif r.get('stage') == 'needs_manual_verify':
                summary['needs_manual_verify'] += 1
            elif r.get('stage') in FAILED_STAGES:
                summary['failed'] += 1

        report = {
            'kind': 'cookie',
            'run_id': run_id,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'run_dir': run_dir,
            'summary': summary,
            'needs_manual_verify': self._collect_manual(results),
            'results': results,
        }
        self._write_report(run_dir, report, COOKIE_REPORT_COLUMNS)
        return report


class BatchRealnameRunner(_BatchRunnerBase):
    """批量审查实名；``submit=True`` 时对需要实名的账号按需提交。"""

    def process_account(self, account, run_dir, index=0, shared_device=None, submit=False):
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

            session = self._acquire_session(auth, account, sauth)
            record['session_source'] = session.get('session_source')
            if session['stage'] != 'session_ready':
                return self._apply_session_failure(record, session)

            record['_device'] = self._device_record(auth)
            record['device_id'] = auth.device_id

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

            # 实名提交只使用账号条目自带的身份，缺失就跳过。
            realname = account.get('realname')
            id_num = account.get('id_num')
            id_region = account.get('id_region', '86')
            record['realname_masked'] = mask_realname(realname)
            record['id_num_masked'] = mask_id_num(id_num)
            if not realname or not id_num:
                record['submit_status'] = 'skipped'
                record['error'] = '需要实名但账号未提供 realname/id_num'
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

    def run(self, accounts, submit=False, delay=0.0, on_progress=None):
        process = lambda account, run_dir, index, shared_device: self.process_account(
            account, run_dir, index, shared_device, submit=submit)
        run_id, run_dir, results = self._run_loop(accounts, delay, on_progress, process)

        summary = {'total': len(results), 'verified': 0, 'required': 0, 'unknown': 0,
                   'submitted': 0, 'submit_failed': 0, 'skipped': 0,
                   'needs_manual_verify': 0, 'failed': 0}
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

            if r.get('stage') == 'needs_manual_verify':
                summary['needs_manual_verify'] += 1
            elif r.get('stage') in FAILED_STAGES:
                summary['failed'] += 1

        report = {
            'kind': 'realname',
            'run_id': run_id,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'submit_enabled': submit,
            'run_dir': run_dir,
            'summary': summary,
            'needs_manual_verify': self._collect_manual(results),
            'results': results,
        }
        self._write_report(run_dir, report, REALNAME_REPORT_COLUMNS)
        return report


__all__ = ['BatchCookieRunner', 'BatchRealnameRunner', 'load_sauth_from_file',
           'COOKIE_REPORT_COLUMNS', 'REALNAME_REPORT_COLUMNS']
