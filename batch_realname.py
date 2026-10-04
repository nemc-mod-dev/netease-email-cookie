#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量实名认证命令行入口。

默认只做「审查」，不会提交任何实名信息；确认报告无误后再加 ``--submit``。

示例::

    # 1) 只审查：列出每个账号是否需要实名
    python batch_realname.py --input accounts.json

    # 2) 确认后提交（仅对需要实名、且提供了实名的账号）
    python batch_realname.py --input accounts.json --submit --delay 2

账号文件见 ``accounts.example.json``。身份信息请勿提交到版本库。
"""

import argparse
import json
import sys

from services.batch_service import BatchRealnameRunner
from services.realname_service import REALNAME_REQUIRED, REALNAME_UNKNOWN, REALNAME_VERIFIED

STATE_LABEL = {
    REALNAME_VERIFIED: '已实名',
    REALNAME_REQUIRED: '需要实名',
    REALNAME_UNKNOWN: '状态未知',
}


def load_accounts(path):
    if path == '-':
        text = sys.stdin.read()
    else:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, dict) and 'accounts' in data:
            data = data['accounts']
        if not isinstance(data, list):
            raise ValueError('账号文件应为 JSON 数组，或 {"accounts": [...]}')
        return data
    except json.JSONDecodeError:
        # 回退到 JSON Lines
        accounts = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                accounts.append(json.loads(line))
        return accounts


def build_parser():
    parser = argparse.ArgumentParser(description='批量审查/提交网易账号实名认证')
    parser.add_argument('--input', required=True, help='账号 JSON 文件，- 表示从 stdin 读取')
    parser.add_argument('--submit', action='store_true', help='审查为需实名的账号时提交实名（默认只审查）')
    parser.add_argument('--delay', type=float, default=2.0, help='账号之间的间隔秒数，默认 2')
    parser.add_argument('--limit', type=int, default=0, help='只处理前 N 个账号（0 表示全部）')
    parser.add_argument('--output', default='artifacts/batch', help='报告输出根目录')
    parser.add_argument('--realname', default='', help='可选：账号未单独提供时的默认实名姓名')
    parser.add_argument('--id-num', default='', help='可选：账号未单独提供时的默认证件号')
    parser.add_argument('--id-region', default='86', help='证件签发地区，默认 86')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    accounts = load_accounts(args.input)
    if args.limit > 0:
        accounts = accounts[:args.limit]
    if not accounts:
        print('没有可处理的账号。', file=sys.stderr)
        return 2

    if args.submit and not (args.realname or any(a.get('realname') for a in accounts)):
        print('警告：--submit 已开启，但没有任何账号提供 realname。', file=sys.stderr)

    print(f'共 {len(accounts)} 个账号，模式：{"提交实名" if args.submit else "仅审查"}')

    def on_progress(index, total, record):
        state = STATE_LABEL.get(record.get('realname_state'), record.get('realname_state'))
        line = f"[{index}/{total}] {record.get('label')} -> {state} ({record.get('stage')})"
        if record.get('submit_status'):
            line += f" submit={record['submit_status']}"
        if record.get('error'):
            line += f" error={record['error']}"
        print(line)

    runner = BatchRealnameRunner(output_root=args.output)
    report = runner.run(
        accounts, submit=args.submit, delay=args.delay,
        default_realname=args.realname, default_id_num=args.id_num, default_id_region=args.id_region,
        on_progress=on_progress,
    )

    summary = report['summary']
    print('\n=== 汇总 ===')
    print(f"总计 {summary['total']} | 已实名 {summary['verified']} | 需要实名 {summary['required']} | 未知 {summary['unknown']}")
    print(f"提交成功 {summary['submitted']} | 提交失败 {summary['submit_failed']} | 跳过 {summary['skipped']} | 处理失败 {summary['failed']}")
    print(f"报告: {report['report_json']}")
    print(f"      {report['report_csv']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
