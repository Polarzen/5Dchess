# 发布 Windows ZIP

[文档目录](../README.md)

玩家下载位置是 [GitHub Releases](https://github.com/Polarzen/5Dchess/releases)，附件名固定为 **5DChess-Windows.zip**，首页的“下载”链接指向最新正式版本。GitHub Packages 用于包注册表，本项目的 ZIP 放在 Releases。

ZIP 包含提交中的完整源码、两个启动入口和使用说明。首次启动自动下载运行组件，因此附件较小；它不是预装所有依赖的离线安装包。普通源码也可通过 GitHub 的 Code → Download ZIP 获取。

## 准备与检查

发布维护者需要 Python 3.11、Git 和已登录的 GitHub CLI。以下操作在仓库根目录进行，普通玩家无需执行。

1. 检查测试及 GitHub Actions，并提交本次准备发布的代码和文档。
2. 用明确的提交或标签打包。脚本只读取 Git 提交，不会混入未提交修改、运行环境或日志。
3. 解压检查 `本地.bat`、`远程.bat`、`使用说明.txt` 和 `VERSION.txt`，核对启动与说明。
4. 将提交推送到 GitHub，再创建带附件的 Release。

示例（替换版本号和提交）：

```powershell
python scripts/release/build_windows.py --ref <commit-sha> --version v0.1.0
```

输出位于 `dist/v0.1.0/`：

- `5DChess-Windows.zip`：解压后根文件夹为 `5DChess`。
- `SHA256SUMS.txt`：附件 SHA-256 校验和。

脚本检查必需文件、批处理 CRLF、PowerShell UTF-8 BOM 和私有目录，并写入版本与完整提交号。同一提交及版本的重复构建结果一致。已存在的输出不会覆盖；需要重建时另指定 `--output` 目录。

## 上传并发布

先写一份说明文件，包含更新内容、首次启动须联网、支持的系统和已知限制，再执行：

```powershell
gh release create v0.1.0 dist/v0.1.0/5DChess-Windows.zip dist/v0.1.0/SHA256SUMS.txt --target <commit-sha> --title "时线棋局 v0.1.0" --notes-file <release-notes-file> --latest
```

最后检查 Release 的 Assets 中有两个附件，下载公开 ZIP 并与本地 SHA-256 对照，确认首页下载入口可以使用。不要把 ZIP 提交进 Git，也不要将本机 `.runtime`、日志或玩家数据打包。

已有 CI 验证代码；由于 GitHub 当前 OAuth 授权缺少 `workflow` 权限，此流程使用手动发布，不依赖新增自动发布工作流。
