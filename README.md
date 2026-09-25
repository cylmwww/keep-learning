# Keep Learning

基于 **LLM Workflow、Kotaemon RAG 与 FSRS** 的个人学习平台，将课程创建、课节学习、间隔复习与查漏测验整合到 Windows 桌面应用中。

输入学习主题或教材，经过资料调研、学习目标问卷、课程蓝图和前三节预览，确认后发布课程；其余课节在学习时按需生成。关键步骤由用户确认和修改。

> 当前版本：2.0.0。项目处于持续开发阶段，面向本地个人使用。说明依据当前实现，不代表所有模型服务和打包环境均已通过验收。

## 功能

| 功能 | 当前实现 |
| --- | --- |
| 课程创建 | 主题或单个教材 → 调研 → 问卷 → 蓝图 → 预览 → 发布；支持继续草稿 |
| 课程学习 | 按单元、讲次、课节组织目录，提供正文、练习、笔记、参考资料和课节 AI 助手 |
| 课程管理 | 管理正式课程、未完成草稿和学习进度 |
| 知识库问答 | 复用 Kotaemon 的资料上传、索引、检索与带引用问答能力 |
| 间隔复习 | 使用 FSRS 调度卡片，保存评分和复习记录 |
| 查漏测验 | 生成题目、批改答案并记录答题结果 |
| 模型配置 | 配置对话服务和独立的 Embedding 服务 |

课程创建属于有人参与的 LLM Workflow。课程内 AI 助手使用课节内容和近期对话；资料库 RAG 在独立的知识问答入口提供。

## 快速开始（Windows）

需要 Git、联网安装依赖的环境和可用的模型服务。桌面窗口使用 PyWebView / Edge WebView2；桌面模式不可用时可使用浏览器。

### 1. 获取源码

将占位地址替换为实际仓库地址：

```powershell
git clone --recurse-submodules https://github.com/xudongzhangjtu-source/keep-learning.git
cd keep-learning
```

已克隆但缺少 Kotaemon 时，执行：

```powershell
git submodule update --init --recursive
```

### 2. 初始化环境

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-local.ps1
```

脚本在项目内准备 uv 和 Python 3.11，按 Kotaemon 锁文件安装依赖，跳过需要额外本机构建工具的 `llama-cpp-python`，补充 FSRS、PyWebView 和分词资源，并在配置不存在时创建 `kotaemon/.env`。首次安装需要联网。

`setup.bat` 是另一种初始化入口，依赖安装策略不同，可能需要本机编译环境；以上步骤以 `setup-local.ps1` 为准。

### 3. 启动与配置

```powershell
.\run.bat
```

进入“模型配置”设置对话模型的 API Base、API Key 和模型名。使用知识库索引时，还需配置可用的 Embedding 模型；对话服务可用不代表其支持 Embedding。

也可以在本机编辑 `kotaemon/.env` 中的 `OPENAI_API_BASE`、`OPENAI_API_KEY`、`OPENAI_CHAT_MODEL`、`OPENAI_EMBEDDINGS_MODEL` 等配置。**真实配置与密钥不要提交到 Git。**

浏览器模式：

```powershell
$env:LE_DESKTOP = '0'
.\run.bat
```

程序默认监听本机回环地址，启动器寻找可用端口。首次启动需加载较多依赖，请等待窗口或浏览器打开。

## 架构与目录

```text
Keep Learning/
├── launcher.py           桌面窗口与后端进程管理
├── custom_app.py         Gradio 后端入口
├── learning_ext/         学习业务、页面、模型调用及前端资源
├── tests/                测试代码
├── docs/ARCHITECTURE.md  当前架构与实现边界
├── setup-local.ps1       本地环境初始化
├── run.bat               启动入口
└── kotaemon/             Git 子模块：RAG 与共享数据底座
```

启动器通过子进程运行 Kotaemon 虚拟环境中的 Python，PyWebView 加载 Gradio 页面。学习数据使用共享的 SQLite 数据库，上传资料与检索索引由 Kotaemon 管理。

详细设计见 [架构文档](docs/ARCHITECTURE.md)。

## 数据与隐私

- `kotaemon/.env`：API 密钥、模型地址等本地配置。
- `kotaemon/ktem_app_data/`：数据库、上传教材、对话与学习记录、文档及向量索引、缓存。
- `.runtime/`、虚拟环境、日志、截图和导出文件：不属于源码交付物，可能包含本机信息或个人内容。

本地存储不等于完全离线：调用远程对话或 Embedding 服务时，相关输入会发送给配置的服务；课程调研也会访问网络。

公开仓库前请阅读 [GitHub 上传与隐私保护规划](docs/GITHUB_UPLOAD_PLAN.md)。`.gitignore` 无法清除已提交的文件或历史内容。

## 开发与测试

学习业务放在 `learning_ext/`，避免直接修改 Kotaemon 底座。模型调用统一通过 `learning_ext.llm.chat/chat_json`，提示词放在对应模块的 `prompts.py`。

安装测试依赖后，在项目根目录运行：

```powershell
.\.runtime\uv\uv.exe pip install --python .\kotaemon\.venv\Scripts\python.exe pytest
Remove-Item Env:RUN_LLM_TESTS -ErrorAction SilentlyContinue
.\kotaemon\.venv\Scripts\python.exe -m pytest tests
```

真实模型测试默认跳过；设置 `RUN_LLM_TESTS=1` 会调用外部服务并可能消耗配额。测试前应备份个人数据并核对测试隔离配置。本次文档更新未执行完整回归或真实模型验证。

## 打包与实现边界

`build_exe.bat` 用于构建启动器，需先在项目虚拟环境中安装 PyInstaller；`pack_portable.bat` 用于组装便携目录。启动器 exe 本身不是包含全部依赖的单文件应用。

便携版脚本不会复制 `.env`，模型密钥需在本机通过配置页另行填写。发布安装包前仍应在干净环境重新构建并检查全部产物，避免把本地教材、数据库或缓存一并带入。

- 课程调研以搜索摘要为主；教材解析暂不支持扫描件 OCR。
- 后台课节任务使用进程内线程池，重启后不会自动续跑。
- 费曼、导出和看板存在服务代码，但尚未全部接入独立可见页面。
- 当前面向本地个人使用，尚未完成面向公网的多用户隔离设计。

后续方向包括任务恢复、资料引用质量、功能入口完善和发布流程验证；独立前端与 RAG 服务拆分属于未来演进。

## 致谢与许可

依赖 [Kotaemon](https://github.com/Cinnamon/kotaemon)、FSRS、Gradio 和 PyWebView 等开源组件。第三方代码遵循各自许可，Kotaemon 许可见子模块中的 `LICENSE.txt`。当前自建代码未添加独立 LICENSE，公开发布前由维护者确定授权方式。
