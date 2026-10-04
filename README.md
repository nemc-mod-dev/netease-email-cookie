# 网易邮箱/Cookie 转换工具

这是一个基于抓包数据分析实现的网易 mkey 登录工具，支持邮箱登录、手机号短信登录、Cookie / SAuth 管理与邮箱信息获取。

## 功能特性

- 网易账号登录验证（邮箱 + 密码 / 手机号 + 短信验证码）
- 设备信息模拟注册与上传
- 1351 安全验证处理（短信验证、状态轮询，不可靠时回退人工验证）
- Cookie / SAuth 自动拼接、保存与导出（NEMC 格式）
- 邮箱消息列表获取
- **批量实名认证**：先审查账号是否需要实名，再按需提交，输出脱敏报告

## 项目结构

```
main.py                     纯控制台入口（子命令 + 交互菜单）
console_ui.py               控制台输出格式化与输入辅助
workflow.py                 AuthWorkflow，编排登录/验证流程
batch_realname.py           批量实名认证命令行（也可用 main.py batch-realname）
services/
  auth_service.py           NetEaseAuthService：设备、登录、SAuth、邮件列表
  verify_service.py         VerifyService：1351 安全验证相关接口
  realname_service.py       RealnameService：实名审查与提交接口
  batch_service.py          BatchRealnameRunner：批量编排与报告
  storage_service.py        StorageService：产物读写与导出
tests/
  test_smoke.py             登录/存储层离线冒烟测试
  test_realname.py          实名接口与批量编排离线测试
  test_console.py           控制台入口离线测试
accounts.example.json       批量账号文件示例
requirements.txt            Python 依赖
artifacts/                  运行产物统一输出目录
```

## 使用方法

### 安装依赖

```
pip install -r requirements.txt
```

### 运行程序

```bash
# 交互式菜单（直接运行即可）
python main.py

# 或用子命令
python main.py login --mode email --identifier you@163.com
python main.py status
python main.py realname-check
python main.py batch-realname --input accounts.json

# 查看全部子命令
python main.py --help
```

子命令：`login` / `verify` / `send-sms` / `realname-check` / `realname-submit` /
`mailbox` / `export` / `device` / `status` / `batch-realname`。不带子命令时进入交互菜单。
密码、证件号等敏感字段建议留空，程序会用 `getpass` 交互读取，避免写入命令历史。

### 操作流程

- **邮箱模式**：`python main.py login --mode email --identifier you@163.com`；如触发安全验证，按提示打开验证链接，完成后用 `python main.py verify --ticket <ticket>` 确认，或登录时加 `--wait` 自动轮询。
- **手机号模式**：`python main.py login --mode phone --identifier 138...`，请求短信后填写验证码提交。
- 转换成功后，产物（SAuth、HTTP Cookies、Cookie 格式、NEMC Cookie）统一写入 `artifacts/` 目录，其中 `nemc_cookie_*.json` 为可复用结果。

### 运行测试

```bash
python -m unittest discover -s tests -v
```

### 批量实名认证

流程是 **先审查、后提交**，默认只审查、绝不会提交任何实名信息。

```bash
# 1) 仅审查：列出每个账号是否需要实名
python batch_realname.py --input accounts.json

# 2) 确认报告无误后，再对「需要实名」的账号提交
python batch_realname.py --input accounts.json --submit --delay 2
```

账号文件格式见 `accounts.example.json`，支持两种会话来源：

- `sauth` / `sauth_file`：直接复用已有会话（如 `artifacts/nemc_cookie_*.json`），跳过登录；
- `identifier` + `password`（邮箱）或 + `sms_code`（手机号）：现场登录换取会话。

审查依据的是抓包确认的接口：`GET .../users/{uid}/info?opt_fields=realname_status`；
提交走 `POST .../realname/verify` + `POST .../realname/update_by_token`。
报告写入 `artifacts/batch/<run_id>/report.json` 与 `report.csv`，其中姓名/证件号**已脱敏**。

## 注意事项

- 如遇安全验证，可能需要手动完成验证流程。
- 一个手机号一天内通常只能完成有限次数的安全验证。
- `artifacts/`、`device_info.json`、`sauth_data.json`、`nemc_cookie_*.json` 含会话凭据，已被 `.gitignore` 忽略，请勿随代码分发或提交。
- **实名认证必须使用本人真实、合法的身份信息**；批量工具仅用于管理你自己的账号，请勿用于他人身份或违规批量注册/交易账号。账号资料文件（`accounts.json`）、抓包文件（`*.har`）含敏感信息，已加入 `.gitignore`。

## 技术实现

- 基于 Python `requests` 实现 HTTP 请求
- 纯标准库控制台（`argparse` + 交互菜单），无 TUI 依赖
- 模拟移动端设备信息和请求头，`pycryptodome` 处理登录参数加密

## 免责声明

本工具仅供学习和研究使用，请勿用于非法用途。使用者应当遵守相关法律法规和网站服务条款。
