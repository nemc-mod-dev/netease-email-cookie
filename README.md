# 网易邮箱/Cookie 转换工具

这是一个基于抓包数据分析实现的网易 mkey 登录工具，支持邮箱登录、手机号短信登录、Cookie / SAuth 管理与邮箱信息获取。

## 功能特性

- 网易账号登录验证（邮箱 + 密码 / 手机号 + 短信验证码）
- 设备信息模拟注册与上传
- 1351 安全验证处理（短信验证、状态轮询，不可靠时回退人工验证）
- Cookie / SAuth 自动拼接、保存与导出（NEMC 格式）
- 邮箱消息列表获取

## 项目结构

```
main.py                     程序入口，启动 Textual 界面
app.py                      Textual TUI（邮箱/手机号两种模式）
workflow.py                 AuthWorkflow，编排登录/验证流程与轮询
view_state.py               UI 状态与展示文本
services/
  auth_service.py           NetEaseAuthService：设备、登录、SAuth、邮件列表
  verify_service.py         VerifyService：1351 安全验证相关接口
  storage_service.py        StorageService：产物读写与导出
tests/
  test_smoke.py             离线冒烟测试（桩响应，不联网）
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
python main.py
```

### 操作流程

- **邮箱模式**：输入邮箱和密码后点击「开始转换」；如触发安全验证，按提示完成验证。
- **手机号模式**：输入手机号请求短信，收到后填写验证码并提交。
- 转换成功后，产物（SAuth、HTTP Cookies、Cookie 格式、NEMC Cookie）统一写入 `artifacts/` 目录，其中 `nemc_cookie_*.json` 为可复用结果。

### 运行测试

```bash
python -m unittest discover -s tests -v
```

## 注意事项

- 如遇安全验证，可能需要手动完成验证流程。
- 一个手机号一天内通常只能完成有限次数的安全验证。
- `artifacts/`、`device_info.json`、`sauth_data.json`、`nemc_cookie_*.json` 含会话凭据，已被 `.gitignore` 忽略，请勿随代码分发或提交。

## 技术实现

- 基于 Python `requests` 实现 HTTP 请求
- 使用 `textual` 构建终端界面
- 模拟移动端设备信息和请求头，`pycryptodome` 处理登录参数加密

## 免责声明

本工具仅供学习和研究使用，请勿用于非法用途。使用者应当遵守相关法律法规和网站服务条款。
