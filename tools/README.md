# 工具说明

本文件是项目辅助工具的统一操作手册，集中维护钉钉导出、批量导出、Markdown 阅读器、服务器同步、部署和排障说明。

## 运行环境

完整流程需要：

- Python 3
- macOS 内置 OpenSSL
- Pillow，用于生成图片缩略图：`pip3 install Pillow`
- 可选的 `pycryptodome`，用于加速 AES 解密：`pip3 install pycryptodome`
- Git
- Node.js
- SSH Key 认证

## 钉钉聊天记录导出

### 配置

项目根目录需要存在本地文件 `client_config.json`，其中包含：

- `dingtalk_path`：钉钉数据目录路径；
- `global_key`：`storage.db` 的 AES 密钥；
- `export_targets`：需要导出的会话 CID 列表。

钉钉客户端必须已在本机运行过，并生成相关数据库文件。

### 导出当天

```bash
cd ~/Downloads/demo/something
python3 tools/export.py
```

也可以明确传入当天日期：

```bash
python3 tools/export.py "$(date +%F)"
```

### 导出指定日期

```bash
python3 tools/export.py 2026-07-02
```

### 批量补导日期范围

```bash
python3 tools/export_range.py 2026-07-01 2026-07-31
```

跳过没有消息的日期：

```bash
python3 tools/export_range.py 2026-07-01 2026-07-31 --skip-empty
```

### 导出结果

```text
exports/YYYY-MM-DD/先知/messages.md
exports/YYYY-MM-DD/先知/images/
exports/YYYY-MM-DD/先知/images/thumbs/
```

- `messages.md` 保存当天导出的 Markdown 消息。
- `images/` 保存原图。
- `images/thumbs/` 保存 JPEG 缩略图。
- 新导出图片会生成缩略图；历史导出没有缩略图时，阅读器自动回退到原图。
- 导出脚本会增量更新阅读器中的原始消息索引。

### 检查导出结果

```bash
TODAY=$(date +%F)
ls -la "exports/$TODAY/先知"
sed -n '1,160p' "exports/$TODAY/先知/messages.md"
find "exports/$TODAY/先知/images" -maxdepth 1 -type f | head
```

如果 `messages.md` 没有消息，依次确认：

1. 钉钉当天数据是否已经同步到本机。
2. `client_config.json` 中的 `export_targets` 是否仍指向正确会话。
3. 日期是否正确，是否需要手动指定日期。
4. 钉钉数据库文件是否存在且可以解密。

如果原图目录为空，可能是当天没有图片、图片下载失败，或消息中没有可解析的图片 ID。

## 先知 Markdown 阅读器

阅读器用于查看原始导出、每日复盘、公众号复盘、月度复盘、长期主题、历史关注清单和跟踪台账。

### 启动与停止

在项目根目录执行：

```bash
node tools/xianzhi-reader/server.mjs
```

默认访问：

```text
http://127.0.0.1:8787
```

如果 `8787` 端口被占用，服务会自动尝试后续端口，并在终端输出实际地址。停止服务时，在启动服务的终端按 `Ctrl+C`。

### 数据来源

| 阅读器分类 | 来源 |
| --- | --- |
| 原始消息 | `exports/YYYY-MM-DD/先知/messages.md` |
| 每日复盘 | `finance/先知/reviews/daily/` |
| 公众号复盘 | `finance/先知/reviews/articles/` |
| 月度和阶段复盘 | `finance/先知/reviews/weekly/` |
| 主题跟踪 | `finance/先知/topics/`、`finance/先知/主题索引.md` |
| 历史关注清单 | `finance/先知/验证清单.md` |
| 跟踪台账 | `finance/先知/跟踪台账.csv` |

阅读器只读取白名单范围内的文件，不修改任何复盘、台账或索引文件。

### 文件索引

阅读器使用 `tools/xianzhi-reader/file-index.json` 保存文件列表。页面加载时只读取索引，不直接扫描 `finance/` 或 `exports/`。

- 索引缺失或损坏时，阅读器启动会自动离线重建。
- 钉钉导出后，导出脚本会增量更新原始消息索引。
- 同步当天 `exports` 或更新服务器代码时，相关脚本会重建服务器索引。
- 手动新增、删除或修改 `finance/` 下的文件后，执行：

```bash
node tools/xianzhi-reader/server.mjs --rebuild-index
```

`file-index.json` 只保留在本地和服务器，不进入 Git。

## SSH Key 认证

`sync_today_exports.sh` 和 `update_reader_server.sh` 默认连接 `root@47.253.178.201`，并复用 `~/.ssh/config` 中的用户和私钥配置：

```sshconfig
Host 47.253.178.201
    HostName 47.253.178.201
    User root
    IdentityFile ~/.ssh/id_ed25519_something
    IdentitiesOnly yes
```

使用脚本前应能直接登录：

```bash
ssh root@47.253.178.201
```

两个脚本均只允许公钥认证，不读取密码，也不会回退到密码登录。需要指定其他目标或私钥时，可以使用命令行参数或环境变量：

```bash
tools/update_reader_server.sh --identity ~/.ssh/id_ed25519_something
DEPLOY_HOST=root@47.253.178.201 DEPLOY_IDENTITY="$HOME/.ssh/id_ed25519_something" tools/sync_today_exports.sh
```

## 同步原始导出到服务器

同步当天目录：

```bash
tools/sync_today_exports.sh
```

同步指定日期：

```bash
tools/sync_today_exports.sh --date 2026-07-06
```

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--host HOST` | 指定 SSH 目标 |
| `--identity FILE` | 指定 SSH 私钥 |
| `--date YYYY-MM-DD` | 指定同步日期，默认当天 |
| `--local-dir DIR` | 指定本地 `exports` 根目录 |
| `--remote-dir DIR` | 指定服务器 `exports` 根目录 |

脚本通过 `tar over ssh` 将以下目录同步到服务器：

```text
本地：exports/YYYY-MM-DD/
远端：/opt/something/exports/YYYY-MM-DD/
```

**同步时会先删除服务器上对应日期目录，再上传本地目录。** 同步完成后，脚本会重建服务器阅读器索引。

## 更新服务器阅读器

普通更新只执行 `git pull` 并重建索引，不安装依赖，也不重启服务：

```bash
tools/update_reader_server.sh
```

更新后重启并校验 HTTP 资源：

```bash
tools/update_reader_server.sh --restart
```

安装依赖、重启、校验资源并查看状态：

```bash
tools/update_reader_server.sh --install --restart --status
```

指定服务器项目目录：

```bash
tools/update_reader_server.sh --remote-dir /opt/something
```

参数说明：

| 参数 | 作用 |
| --- | --- |
| `--host HOST` | 指定 SSH 目标 |
| `--identity FILE` | 指定 SSH 私钥 |
| `--remote-dir DIR` | 指定服务器项目目录 |
| `--install` | 根据锁文件执行 `npm ci` 或 `npm install --package-lock=false` |
| `--restart` | 重启服务并校验首页及 Markdown 静态资源 |
| `--status` | 输出 systemd 服务状态 |

## 服务器配置与排障

### 服务器信息

```text
服务器：47.253.178.201
用户：root
项目目录：/opt/something
阅读器入口：/opt/something/tools/xianzhi-reader/server.mjs
systemd 服务：xianzhi-reader.service
服务端口：18787
Git remote：git@github.com:littlechaw/something.git
```

服务器 `/opt/something` 使用 GitHub SSH remote。拉取失败时先检查认证：

```bash
ssh root@47.253.178.201 'ssh -T git@github.com'
```

### systemd 操作

```bash
ssh root@47.253.178.201 'systemctl restart xianzhi-reader.service'
ssh root@47.253.178.201 'systemctl stop xianzhi-reader.service'
ssh root@47.253.178.201 'systemctl status xianzhi-reader.service --no-pager -l'
```

服务文件位于：

```text
/etc/systemd/system/xianzhi-reader.service
```

关键配置：

```text
WorkingDirectory=/opt/something
Environment=PORT=18787
ExecStart=/usr/bin/node /opt/something/tools/xianzhi-reader/server.mjs
Restart=always
```

## 本地忽略与安全注意事项

以下内容只保留在本地或指定服务器，不进入 Git：

```gitignore
.gitignore
.DS_Store
client_config.json
.dec_data/
exports/
.claude/
tools/xianzhi-reader/file-index.json
```

- `client_config.json` 和 `.dec_data/` 包含解密配置或临时数据，不得提交。
- `exports/` 可能包含聊天记录、图片和身份信息，同步或分享前应确认内容范围。
- 本项目的 `.gitignore` 本身不由 Git 跟踪；协作者需要在本地维护对应忽略规则。
