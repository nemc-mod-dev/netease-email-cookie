# 网易账号批量工具

把一批网易账号批量转成可复用 Cookie，或批量做**实名审查/提交**的纯控制台工具。

定位很明确：**输入一批账号 → 执行一个动作 → 输出每账号结果**。
没有"主账号"，没有跨运行的会话；每个账号在自己的处理步骤里独立登录。

## 功能特性

- 批量转 Cookie / SAuth（含 NEMC Cookie 格式）
- 批量实名：**先审查是否需要实名，再按需提交**，输出脱敏报告
- 1351 安全验证：**跳过并汇总**待人工处理的账号，不阻塞整批
- 账号来源支持控制台粘贴、文本文件、JSON / JSON Lines
- 同一批次共享设备上下文，减少重复注册

## 项目结构

```
main.py                     唯一入口（子命令 + 交互菜单）
console_ui.py               控制台输入/输出原语
services/
  auth_service.py           NetEaseAuthService：设备、登录、SAuth
  verify_service.py         VerifyService：1351 安全验证相关接口
  realname_service.py       RealnameService：实名审查与提交接口
  batch_service.py          BatchCookieRunner / BatchRealnameRunner
  account_input.py          账号输入解析（---- / JSON / JSONL）
  storage_service.py        产物读写与导出
tests/
  test_smoke.py             登录/存储层离线冒烟测试
  test_realname.py          实名接口与批量编排离线测试
  test_batch_cookie.py      批量转 Cookie 编排离线测试
  test_account_input.py     账号解析离线测试
  test_console.py           控制台入口离线测试
  test_console_ui.py        排版层（宽度/对齐/颜色/表格）离线测试
accounts.example.json       JSON 账号清单示例
accounts.example.txt        纯文本账号清单示例
requirements.txt            Python 依赖
artifacts/                  产物与批量报告输出目录
```

## 安装与运行

```bash
pip install -r requirements.txt

# 交互式菜单（直接运行）
python main.py

# 子命令
python main.py cookies  --input accounts.txt          # 批量转 Cookie
python main.py realname --input accounts.txt          # 批量审查实名（默认只审查）
python main.py realname --input accounts.txt --submit # 审查后按需提交
python main.py result                                 # 查看最近一次结果
python main.py --help
```

`--input -` 表示从标准输入读取，例如：

```bash
cat accounts.txt | python main.py cookies --input -
```

## 账号格式

**纯文本（推荐，方便粘贴）**，每行一条，`#` 开头为注释：

```
邮箱----密码
邮箱----密码----姓名----证件号      # 提交实名时需要
```

**JSON / JSON Lines**（可带 `sauth` / `sauth_file` / `sms_code` / `mode` 等字段）：

```json
[
  {"identifier": "user@163.com", "password": "pw"},
  {"identifier": "user2@163.com", "sauth_file": "artifacts/nemc_cookie_x.json"},
  {"identifier": "user3@163.com", "password": "pw", "realname": "张三", "id_num": "110101199001011237"}
]
```

字段说明见 `services/batch_service.py` 顶部注释。

## 批量行为

- **转 Cookie**：每个账号登录成功后，产物写入
  `artifacts/batch/<run_id>/accounts/<账号>/`，报告汇总在 `report.json` / `report.csv`。
- **实名**：先 `GET .../info?opt_fields=realname_status` 审查；
  - 已实名 → 跳过；
  - 需要实名且 `--submit` 且账号条目自带身份 → 提交（`realname/verify` + `realname/update_by_token`）；
  - 需要实名但**没有身份** → 标记 `skipped`，不提交；
  - 状态未知 → 不自动提交。
- **1351 安全验证**：需要人工完成的账号记为 `needs_manual_verify`，
  汇总写入 `artifacts/batch/<run_id>/needs_verify.json`（含 ticket 与验证链接），整批继续。
- 报告中的姓名/证件号一律**脱敏**（如 `张*`、`110***********1237`），不落盘完整身份信息。

## 身份边界

批量**审查**实名可以随意跑。批量**提交**只使用每个账号条目自带的真实身份，
程序**不提供**"填一次身份刷所有账号"的全局选项；缺失身份的账号会被跳过。

## 控制台外观

界面自带统一排版：分区标题（`▍`）、分隔线、对齐表格、状态徽标与图例。
颜色按语义固定：**绿＝成功、黄＝需处理、红＝失败、灰＝跳过**，启动时打印图例对照。

- 颜色自动检测：输出到终端时开启；重定向到管道/文件时自动关闭。
  - `NO_COLOR=1` 强制关闭，`FORCE_COLOR=1` 强制开启。
- 制表符宽度按 1 计算；若你的终端把框线渲染成双宽导致错位，设 `CONSOLE_AMBIGUOUS_WIDE=1`。

## 运行测试

```bash
python -m unittest discover -s tests -v
```

## 注意事项

- 如遇安全验证，需要人工完成对应账号的验证流程后才能继续处理。
- 一个手机号一天内通常只能完成有限次数的安全验证。
- `artifacts/`、`device_info.json`、`sauth_data.json`、`nemc_cookie_*.json` 含会话凭据；
  账号清单（`accounts.txt` / `accounts.json`）、抓包文件（`*.har`）含敏感信息，均已被 `.gitignore` 忽略。
- **实名认证必须使用本人真实、合法的身份信息**；本工具仅用于管理你自己的账号。

## 技术实现

- 基于 Python `requests` 实现 HTTP 请求
- 纯标准库控制台（`argparse` + 交互菜单），无 TUI 依赖
- 模拟移动端设备信息和请求头，`pycryptodome` 处理登录参数加密

## 免责声明

本工具仅供学习和研究使用，请勿用于非法用途。使用者应当遵守相关法律法规和网站服务条款。
