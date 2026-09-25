$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.runtime\python'
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.runtime\uv-cache'
$uv = Join-Path $PSScriptRoot '.runtime\uv\uv.exe'
if (!(Test-Path -LiteralPath $uv)) {
    New-Item -ItemType Directory -Force '.runtime' | Out-Null
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile '.runtime\uv.zip'
    Expand-Archive -LiteralPath '.runtime\uv.zip' -DestinationPath '.runtime\uv' -Force
}
Push-Location 'kotaemon'
try {
    & $uv sync --python 3.11 --locked --no-install-package llama-cpp-python
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $uv pip install --python '.venv\Scripts\python.exe' fsrs==6.3.2 pywebview==6.2.1
    if ($LASTEXITCODE -ne 0) { throw 'Learning dependencies installation failed.' }
    & '.venv\Scripts\python.exe' -m nltk.downloader -d '.venv\Lib\site-packages\llama_index\core\_static\nltk_cache' punkt_tab stopwords punkt
    if ($LASTEXITCODE -ne 0) { throw 'NLTK data download failed.' }
    $env:TIKTOKEN_CACHE_DIR = Join-Path $PSScriptRoot '.runtime\tiktoken'
    & '.venv\Scripts\python.exe' -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
    if ($LASTEXITCODE -ne 0) { throw 'Tokenizer download failed.' }
} finally {
    Pop-Location
}
if (!(Test-Path -LiteralPath 'kotaemon\.env')) {
    @'
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=deepseek-chat
OPENAI_EMBEDDINGS_MODEL=
KH_GRADIO_SHARE=false
KH_ENABLE_FIRST_SETUP=false
KH_FEATURE_USER_MANAGEMENT=false
'@ | Set-Content -LiteralPath 'kotaemon\.env' -Encoding utf8
}
Write-Host 'Setup complete. Double-click run.bat to start.'
