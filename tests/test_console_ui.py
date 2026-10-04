#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""控制台排版层测试：宽度、对齐、颜色开关、表格、确认语法。"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import console_ui as ui


class WidthTest(unittest.TestCase):
    def test_cjk_counts_as_two(self):
        self.assertEqual(ui.display_width('总计'), 4)
        self.assertEqual(ui.display_width('abc'), 3)
        self.assertEqual(ui.display_width('总计 ab'), 7)

    def test_ansi_ignored_in_width(self):
        ui.set_color(True)
        try:
            self.assertEqual(ui.display_width(ui.style('总计', 'red')), 4)
        finally:
            ui.set_color(False)

    def test_pad_aligns(self):
        self.assertEqual(ui.pad('总计', 6), '总计  ')
        self.assertEqual(ui.pad('总计', 6, 'right'), '  总计')
        self.assertEqual(ui.pad('ab', 6, 'center'), '  ab  ')

    def test_truncate_adds_ellipsis_and_respects_width(self):
        long = 'a' * 20
        out = ui.truncate(long, 10)
        self.assertEqual(ui.display_width(out), 10)
        self.assertTrue(out.endswith('…'))
        # 中日韩宽度
        out2 = ui.truncate('中文中文中文', 5)
        self.assertLessEqual(ui.display_width(out2), 5)

    def test_ambiguous_width_switch(self):
        self.assertEqual(ui._char_width('─'), 1)
        ui.AMBIGUOUS_WIDE = True
        try:
            self.assertEqual(ui._char_width('─'), 2)
            self.assertEqual(ui._char_width('中'), 2)
            self.assertEqual(ui._char_width('a'), 1)
        finally:
            ui.AMBIGUOUS_WIDE = False


class ColorTest(unittest.TestCase):
    def test_style_off_is_plain(self):
        ui.set_color(False)
        self.assertEqual(ui.style('x', 'red', 'bold'), 'x')

    def test_style_on_adds_codes(self):
        ui.set_color(True)
        try:
            out = ui.style('x', 'red')
            self.assertIn('\033[31m', out)
            self.assertTrue(out.endswith('\033[0m'))
        finally:
            ui.set_color(False)

    def test_badge_has_symbol(self):
        ui.set_color(False)
        self.assertEqual(ui.badge('成功', 'success'), '✔ 成功')
        self.assertEqual(ui.badge('失败', 'error'), '× 失败')


class RenderTest(unittest.TestCase):
    def _capture(self, func, *args, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf):
            func(*args, **kwargs)
        return buf.getvalue()

    def test_table_columns_aligned(self):
        out = self._capture(ui.table, ['#', '账号'], [[1, 'a@163.com'], [2, 'bb@163.com']],
                            aligns=['right', 'left'])
        lines = out.splitlines()
        self.assertEqual(len(lines), 4)  # 表头 + 分隔线 + 2 行
        self.assertIn('─', lines[1])
        # 账号列在所有数据行起始位置一致
        offsets = {l.index('@163.com') - len(name) for l, name in zip(lines[2:4], ['a', 'bb'])}
        self.assertEqual(len(offsets), 1, offsets)

    def test_menu_renders_hints(self):
        out = self._capture(ui.menu, [('1', '批量转 Cookie', '说明'), ('0', '退出')], '主菜单')
        self.assertIn('主菜单', out)
        self.assertIn('批量转 Cookie', out)
        self.assertIn('说明', out)

    def test_section_and_divider(self):
        out = self._capture(ui.section, '汇总')
        self.assertIn('汇总', out)
        self.assertIn('─', out)

    def test_banner_box(self):
        out = self._capture(ui.banner, '标题', '副标题')
        lines = out.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith('╭'))
        self.assertTrue(lines[-1].startswith('╰'))
        self.assertTrue(all(ui.display_width(l) == ui.content_width() for l in lines))


class ConfirmTest(unittest.TestCase):
    def _answer(self, value, default=True):
        with mock.patch.object(ui, '_ask_raw', return_value=value):
            return ui.confirm('继续？', default=default)

    def test_numeric_one_is_yes(self):
        self.assertTrue(self._answer('1'))

    def test_letters(self):
        self.assertTrue(self._answer('y'))
        self.assertTrue(self._answer('是'))
        self.assertFalse(self._answer('n'))
        self.assertFalse(self._answer('0'))

    def test_empty_uses_default(self):
        self.assertTrue(self._answer('', default=True))
        self.assertFalse(self._answer('', default=False))


class MultilineTest(unittest.TestCase):
    def test_stops_at_blank_line(self):
        answers = iter(['a@163.com----pw', 'b@163.com----pw', ''])
        with mock.patch.object(ui, '_ask_raw', side_effect=lambda *_: next(answers)):
            text = ui.read_multiline()
        self.assertEqual(text, 'a@163.com----pw\nb@163.com----pw')


if __name__ == '__main__':
    unittest.main()
