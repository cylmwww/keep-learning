# GitHub 上传与隐私保护规划

检查日期：2026-09-25。目标：发布可重建的源码，将个人配置、教材与学习记录留在本机。

本次仅编辑文档与忽略规则，没有上传、推送、删除本地数据、修改暂存区或改写 Git 历史。以下命令是后续操作方案，不代表已经执行。

## 1. 已发现的风险

| 当前情况 | 上传前处理 |
| --- | --- |
| `docs/learning_routes/` 已被 Git 跟踪，含个人学习目标命名的 JSON 和 manifest | 首次公开建议从干净目录重建仓库；新加忽略规则无法清理历史 |
| `kotaemon/.env` 为实际运行配置 | 不复制、不提交，配置页截图也应检查密钥和接口地址 |
| `kotaemon/ktem_app_data/` 保存用户数据 | 排除整个目录，不能仅排除数据库文件 |
| `pack_portable.bat` 原先会复制根目录 `.env` | 本次已删除这条复制命令；发布便携包前仍须在干净环境检查全部产物 |
| `docs/frontend-v1-evidence/` 和本机验收、修复报告 | 首次不上传；截图、日志和文字须逐项脱敏 |
| `kotaemon` 为 Git 子模块（mode `160000`） | 保留版本引用，不展开复制本机整个底座目录 |

`.gitmodules` 指向 `https://github.com/Cinnamon/kotaemon.git`，父仓库记录提交 `9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9`。本次未联网验证该提交能否重新拉取，发布前应通过干净克隆确认。

## 2. 建议上传的白名单

| 路径 | 建议与检查点 |
| --- | --- |
| `learning_ext/` | 上传业务源码与必要前端资源；排除缓存和数据，检查硬编码凭据 |
| `tests/` | 上传测试代码；样例使用合成数据，不能包含真实教材和账号 |
| `launcher.py`、`custom_app.py` | 上传桌面和后端入口 |
| `setup-local.ps1`、`setup.bat`、`run.bat`、`start.bat`、`stop-local.py` | 上传初始化和运行工具；检查私人路径和下载地址 |
| `build_exe.bat`、`pack_portable.bat`、`version_info.txt` | 上传打包源码；不代表其生成产物可以直接分发 |
| `README.md`、`.gitignore`、`.gitmodules` | 上传说明、忽略规则和子模块映射 |
| `kotaemon` 子模块引用 | 上传 Git 引用，不上传本机环境和数据 |
| `docs/ARCHITECTURE.md`、`docs/GITHUB_UPLOAD_PLAN.md` | 首次上传的公共文档 |
| `AGENTS.md` | 可选，先检查本机路径和内部信息 |
| `LOCAL_DEPLOYMENT.md`、其余 `docs/` 报告和方案 | 首次暂不上传，逐份脱敏后再加入 |
| `sample_content.md`、`regen_all.py` | 首次暂不上传，单独核对内容来源、个人信息与维护操作范围 |
| 将来新增的 `.env.example` | 仅纯占位模板可上传，不直接复制真实配置 |

未列入白名单的新文件默认待审阅。不应笼统排除所有 JSON，因为代码和测试可能需要 JSON；个人导出按目录排除。

## 3. 必须排除的内容

| 类别 | 路径或模式 | 风险 |
| --- | --- | --- |
| 环境配置 | `.env`、`.env.*`、`*.env` 及配置备份 | API 密钥、私有服务地址、代理信息；人工审核的模板例外 |
| 用户数据 | 任意层级 `ktem_app_data/` | 学习数据库、教材、分块、向量、对话、笔记、答题和复习记录 |
| 数据库及备份 | `*.db`、`*.sqlite`、`*.sqlite3`、WAL/SHM、`*.bak` | 完整数据或已删除记录的残留 |
| 个人课程导出 | `docs/learning_routes/` | 个人目标、课程内容及项目标识 |
| 验收证据 | `docs/frontend-v1-evidence/`，其他截图、录屏和日志 | 用户内容、模型配置、本机用户名及路径 |
| 环境与缓存 | `.runtime/`、`.venv/`、`__pycache__/`、`.pytest_cache/`、`.theflow/`、`.tmp/` | 机器相关文件和运行内容 |
| 构建产物 | `build/`、`dist/`、个人 ZIP 和便携版 | 可能将敏感文件再次打包，忽略规则不检查包内内容 |
| 凭据文件 | 私钥、私钥证书容器、凭据 JSON、令牌文本 | 文件名不一定含 key/token，必须检查内容 |

父仓库忽略规则不管理子模块内部提交。不要在 `kotaemon/` 内无差别执行 `git add .`，也不要删除它的 `.git` 后上传整个目录。

## 4. 忽略规则与历史的区别

本次在原 `.gitignore` 上补充环境配置变体、数据库及备份、私钥、运行缓存、个人路线导出及前端证据的排除规则，保留 `.env.example` 模板入口。

规则只防止匹配的未跟踪文件被常规暂存，不影响已跟踪文件，也不保护网页手工上传、Release 附件和压缩包。

如果决定继续使用当前仓库，可执行以下命令停止跟踪个人导出，磁盘上的文件仍保留：

```powershell
git rm -r --cached -- docs/learning_routes
```

提交此变更后，旧提交仍然含有原内容。**仅停止跟踪，不足以安全发布现有历史。** 本次未执行该命令。

## 5. 上传到截图所示的仓库

目标地址为 `https://github.com/xudongzhangjtu-source/keep-learning`。用户截图显示仓库为公开仓库，已有一个初始提交及 `LICENSE`、`README.md`。因此保留目标库已有提交和 MIT 许可，只把经过审阅的源码快照加入该仓库；不复制当前工作区的 `.git`，不强推或覆盖远程历史。

1. 在项目目录之外建立干净准备目录；按第 2 节白名单复制源码，`learning_ext/` 和 `tests/` 只复制代码及必要资源，`docs/` 首次只复制架构文档和本规划。
2. 克隆指定目标库及其子模块，保留目标库已有文件：

   ```powershell
   git clone --recurse-submodules https://github.com/xudongzhangjtu-source/keep-learning.git keep-learning-publish
   ```

   将白名单源码复制到该干净克隆时，保留现有 `LICENSE`，再审阅 README 的最终内容。按当前项目基线固定 Kotaemon 子模块版本 `9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9`。若克隆时无法访问仓库或子模块，停止远程变更并先解决访问问题；不要另建仓库或换用其他远程。

3. 在克隆目录按白名单暂存并逐项审阅：

   ```powershell
   git add -- .gitignore .gitmodules README.md launcher.py custom_app.py
   git add -- setup-local.ps1 setup.bat run.bat start.bat stop-local.py
   git add -- build_exe.bat pack_portable.bat version_info.txt
   git add -- learning_ext tests docs/ARCHITECTURE.md docs/GITHUB_UPLOAD_PLAN.md kotaemon
   git diff --cached --name-status
   git diff --cached --stat
   git diff --cached --check
   git diff --cached
   ```

4. 第 6 节检查全部完成后提交，并仅以 fast-forward 方式推送到 `main`。如远程有新的提交导致无法 fast-forward，先停止并查看差异，再用新分支提交；不使用 `--force`。
5. 在另一个空目录执行 `git clone --recurse-submodules`，验证依赖安装与启动并单独记录结果。

当前本地项目的 `origin` 指向另一个仓库，因此不可沿用。截图所示目标在本次执行时通过 Git 返回 `Repository not found`，未登录的网页也显示 404；应先核实地址仍有效且有推送权限，再执行克隆和推送。现有私人历史不会被复制到这次提交中。

## 6. 发布前检查清单

- [ ] 暂存区只有白名单源码；`git ls-files --stage kotaemon` 显示 `160000`。
- [ ] `git ls-files` 中没有真实配置、数据库、教材、学习导出、缓存与截图。
- [ ] 在父仓库执行 `git check-ignore -v --no-index .env .env.local docs/learning_routes/manifest.json`；子模块内路径用 `git -C kotaemon check-ignore -v .env ktem_app_data/user_data/sql.db` 检查。
- [ ] 逐项查看暂存差异中的密钥、令牌、密码、邮箱、私有 URL、本机用户名和个人背景。检查输出不要贴到公开 Issue。
- [ ] 使用专门的密钥扫描工具（如 Gitleaks）检查准备发布的内容，同时人工审阅。规则无命中不代表没有泄露。
- [ ] 沿用历史时，检查全部拟发布历史和作者邮箱；若真实密钥曾公开，先撤销或轮换，再处理历史。
- [ ] 图片逐张审阅；不展示真实教材、个人课程、账号或接口配置。
- [ ] 暂不上传便携包和 ZIP。打包脚本已移除复制 `.env` 的行为；发布前仍需审核递归复制目录，使用干净构建环境并解包检查。
- [ ] 保留第三方许可文件；自建代码许可证由维护者决定。
- [ ] 干净克隆能够获取子模块，完成安装与启动验证；文档检查不等于运行验收。

## 7. 本次检查范围与结论

已核对目录、当前 Git 跟踪列表、子模块形式、忽略规则、启动与打包脚本及数据存储路径。对工作区非底座、非运行环境的可见文本检索了常见 OpenAI/GitHub 令牌与私钥头特征，未发现这些特征命中。

该检索未读取真实 `.env`，未覆盖所有密钥格式、已忽略文件、完整 Git 历史、图片和压缩包。当前已发现被跟踪的个人导出，因此不能认定现有仓库可以直接公开推送。完成白名单重建和发布前检查后，再执行上传。
