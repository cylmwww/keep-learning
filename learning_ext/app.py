"""Keep Learning 的主 App。

继承 Kotaemon 的 App，在原 Tab 基础上插入学习特化 Tab：
    首页 | 我的课程 | 课程管理 | 知识问答 | 间隔复习 | 查漏测验 | 资料库 | 模型配置 | 使用指南 | 帮助
"""

from __future__ import annotations

import logging
from pathlib import Path

import gradio as gr
from decouple import config
from ktem.main import App as KotaemonApp
from theflow.settings import settings as flowsettings

from learning_ext import APP_NAME, __version__

logger = logging.getLogger(__name__)

KH_DEMO_MODE = getattr(flowsettings, "KH_DEMO_MODE", False)
KH_SSO_ENABLED = getattr(flowsettings, "KH_SSO_ENABLED", False)

# 旧版底座兼容样式
BEAUTIFY_CSS = """
<style>
:root {
    --le-primary: #4F46E5;
    --le-primary-light: #818CF8;
    --le-primary-dark: #3730A3;
    --le-bg: #F3F4F6;
    --le-card: #FFFFFF;
    --le-border: #E5E7EB;
    --le-text: #111827;
    --le-text-muted: #6B7280;
    --le-success: #10B981;
    --le-warning: #F59E0B;
    --le-danger: #EF4444;
    --le-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --le-shadow-md: 0 4px 6px -1px rgba(0,0,0,0.08), 0 2px 4px -2px rgba(0,0,0,0.05);
    --le-radius: 12px;
}

/* ===== 全局字体 ===== */
html, body, .gradio-container, .gradio-container * {
    font-family: -apple-system, BlinkMacSystemFont, "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Segoe UI", Roboto, sans-serif !important;
}

/* ===== 主容器 ===== */
.gradio-container {
    max-width: 100% !important;
    padding: 0 !important;
    background: var(--le-bg) !important;
    min-height: 100vh;
}
footer {display:none !important;}

#le-navigation-toggle {
    position: fixed;
    left: calc(var(--le-sidebar-width) - 36px);
    bottom: 12px;
    z-index: 30;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    min-width: 28px;
    height: 32px;
    padding: 4px !important;
    border: none !important;
    border-radius: 4px !important;
    background: var(--le-card) !important;
    color: var(--le-text-muted) !important;
    box-shadow: none !important;
    cursor: pointer;
}
#le-navigation-toggle:hover {
    color: var(--le-primary) !important;
    background: #EEF2FF !important;
}
#le-navigation-toggle svg {width: 20px; height: 20px;}
#learning-navigation.le-sidebar-collapsed #le-navigation-toggle {left: 4px;}
#learning-navigation.le-sidebar-collapsed #le-navigation-toggle svg {transform: rotate(180deg);}
#le-navigation-toggle:focus-visible {
    outline: 2px solid var(--le-primary);
    outline-offset: 2px;
}
#learning-navigation.le-sidebar-collapsed {
    grid-template-columns: 0 minmax(0, 1fr);
}
#learning-navigation.le-sidebar-collapsed > .tab-nav {
    display: none !important;
}
#learning-navigation {
    --le-sidebar-width: 200px;
    display: grid !important;
    grid-template-columns: var(--le-sidebar-width) minmax(0, 1fr);
    align-items: start;
    gap: 0 !important;
    min-height: 100vh;
}
#learning-navigation > .tab-nav {
    grid-column: 1;
    grid-row: 1;
    background: var(--le-card) !important;
    border-bottom: none !important;
    border-right: 1px solid var(--le-border) !important;
    padding: 20px 12px 56px !important;
    position: sticky !important;
    top: 0 !important;
    height: 100vh;
    height: 100dvh;
    box-sizing: border-box;
    box-shadow: var(--le-shadow) !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
    justify-content: flex-start !important;
    gap: 6px !important;
    flex-wrap: nowrap !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    scrollbar-width: thin;
}
#learning-navigation > .tab-nav > button {
    flex: 0 0 auto !important;
    width: 100% !important;
    text-align: left !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    padding: 13px 14px !important;
    border: none !important;
    border-left: 3px solid transparent !important;
    border-radius: 8px !important;
    background: transparent !important;
    color: var(--le-text-muted) !important;
    transition: all 0.2s ease !important;
    white-space: nowrap !important;
    margin: 0 !important;
}
#learning-navigation > .tab-nav > button:hover {
    color: var(--le-primary) !important;
    background: rgba(79,70,229,0.06) !important;
}
#learning-navigation > .tab-nav > button.selected {
    color: var(--le-primary) !important;
    border-left-color: var(--le-primary) !important;
    background: #EEF2FF !important;
    font-weight: 700 !important;
}
#learning-navigation > .tab-nav > button:focus-visible {
    outline: 2px solid var(--le-primary-light) !important;
    outline-offset: -2px;
}
#learning-navigation > .tabitem {
    grid-column: 2;
    grid-row: 1;
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    border: none !important;
}
#learning-navigation > .tabitem.scrollable {
    height: 100vh !important;
    height: 100dvh !important;
    max-height: 100vh !important;
    max-height: 100dvh !important;
}
@media (max-width: 900px) {
    #learning-navigation {--le-sidebar-width: 160px;}
    #learning-navigation > .tab-nav {padding: 16px 8px 56px !important;}
    #learning-navigation > .tab-nav > button {padding: 12px 8px !important;}
    #learning-navigation > .tabitem {padding: 20px !important;}
}
@media (max-width: 600px) {
    #learning-navigation {--le-sidebar-width: 124px;}
    #learning-navigation > .tab-nav {padding: 12px 6px 56px !important;}
    #learning-navigation > .tab-nav > button {
        padding: 12px 6px !important;
        font-size: 12px !important;
        white-space: normal !important;
    }
    #learning-navigation > .tabitem {padding: 16px 12px !important;}
}

/* ===== 内容区域 ===== */
#chat-area {
    flex-wrap: nowrap !important;
    height: auto !important;
    min-height: var(--main-area-height);
}
#chat-settings-expand {
    display: flex !important;
    flex-wrap: wrap;
    gap: 8px;
}
#chat-settings-expand > button.label-wrap {
    order: 0;
    width: 100%;
}
#chat-settings-expand > #citation-dropdown,
#chat-settings-expand > #use-mindmap-checkbox {
    position: relative;
    inset: auto;
    height: auto;
    width: auto;
    min-width: 140px !important;
    flex: 1 1 140px;
    order: 1;
}
#chat-settings-expand > div:last-child {
    order: 2;
    width: 100%;
}
#suggest-chat-checkbox {min-width: 95px !important;}

.tabitem {
    padding: 24px 32px !important;
    max-width: 1400px;
    margin: 0 auto;
}

/* ===== 卡片/区块 ===== */
.gradio-container .form,
.gradio-container .gr-block,
.gradio-container .gr-box,
.gradio-container .gradio-accordion,
.gradio-container .gr-form,
.gradio-container .wrap:not(.tab-nav):not(.gap) {
    border-radius: var(--le-radius) !important;
    border: 1px solid var(--le-border) !important;
    background: var(--le-card) !important;
    box-shadow: var(--le-shadow) !important;
}
.gradio-container .gradio-accordion {
    overflow: hidden;
}

/* ===== 输入框 ===== */
.gradio-container input[type="text"],
.gradio-container input[type="password"],
.gradio-container input[type="number"],
.gradio-container textarea,
.gradio-container select {
    border-radius: 8px !important;
    border: 1px solid var(--le-border) !important;
    font-size: 14px !important;
    transition: all 0.2s !important;
}
.gradio-container input[type="text"]:focus,
.gradio-container input[type="password"]:focus,
.gradio-container textarea:focus,
.gradio-container select:focus {
    border-color: var(--le-primary-light) !important;
    box-shadow: 0 0 0 3px rgba(79,70,229,0.12) !important;
}

/* ===== 按钮 ===== */
.gradio-container button.primary,
.gradio-container button[data-testid="submit-button"] {
    background: linear-gradient(135deg, var(--le-primary) 0%, var(--le-primary-light) 100%) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    color: white !important;
    padding: 10px 20px !important;
    box-shadow: 0 2px 8px rgba(79,70,229,0.25) !important;
    transition: all 0.2s !important;
    font-size: 14px !important;
}
.gradio-container button.primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 14px rgba(79,70,229,0.35) !important;
}
.gradio-container button.primary:active {
    transform: translateY(0) !important;
}
/* stop/危险按钮 */
.gradio-container button[variant="stop"],
.gradio-container .stop {
    background: var(--le-danger) !important;
    color: white !important;
}
/* 次按钮 */
.gradio-container button:not(.primary):not([variant="stop"]):not(.tool):not(.icon-button) {
    border-radius: 8px !important;
    border: 1px solid var(--le-border) !important;
    background: var(--le-card) !important;
    color: var(--le-text) !important;
    font-weight: 500 !important;
    padding: 10px 20px !important;
    transition: all 0.2s !important;
    font-size: 14px !important;
}
.gradio-container button:not(.primary):not([variant="stop"]):not(.tool):not(.icon-button):hover {
    border-color: var(--le-primary-light) !important;
    color: var(--le-primary) !important;
    background: rgba(79,70,229,0.04) !important;
}

/* ===== Markdown 渲染 ===== */
.gradio-container .prose, .gradio-container .md {
    font-size: 14.5px !important;
    line-height: 1.7 !important;
    color: var(--le-text) !important;
    max-width: none !important;
}
.gradio-container h1 {
    color: var(--le-text) !important;
    font-weight: 700 !important;
    font-size: 26px !important;
    margin-top: 0 !important;
    padding-bottom: 10px !important;
    border-bottom: 2px solid var(--le-primary) !important;
}
.gradio-container h2 {
    color: var(--le-text) !important;
    font-weight: 700 !important;
    font-size: 20px !important;
    border-left: 4px solid var(--le-primary) !important;
    padding-left: 12px !important;
}
.gradio-container h3 {
    color: var(--le-text) !important;
    font-weight: 600 !important;
    font-size: 17px !important;
}
.gradio-container blockquote {
    background: #EEF2FF !important;
    border-left: 4px solid var(--le-primary) !important;
    padding: 12px 16px !important;
    border-radius: 0 8px 8px 0 !important;
    color: var(--le-text) !important;
    margin: 12px 0 !important;
}
.gradio-container blockquote p {margin: 0 !important;}
.gradio-container code {
    background: #F3F4F6 !important;
    color: var(--le-primary-dark) !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-size: 13px !important;
    font-family: "JetBrains Mono", Consolas, Monaco, monospace !important;
}
.gradio-container pre {
    border-radius: 8px !important;
    border: 1px solid var(--le-border) !important;
}
.gradio-container ul, .gradio-container ol {padding-left: 24px !important;}
.gradio-container li {margin: 4px 0 !important;}

/* ===== 表格/Dataframe ===== */
.gradio-container table, .gradio-container .gradio-dataframe {
    border-radius: 8px !important;
    overflow: hidden !important;
}
.gradio-container table thead {
    background: var(--le-primary) !important;
    color: white !important;
}
.gradio-container table th {
    color: white !important;
    font-weight: 600 !important;
}
.gradio-container table tr:nth-child(even) {
    background: #F9FAFB !important;
}
#learning-project-list .table-wrap {
    height: 360px !important;
    min-height: 360px !important;
    max-height: 360px !important;
    overflow: auto !important;
    scrollbar-gutter: stable;
}
#learning-project-list table {
    overflow: visible !important;
    border-radius: 0 !important;
}
#learning-project-list thead {
    position: sticky;
    top: 0;
    z-index: 2;
}
#learning-project-list thead,
#learning-project-list thead th,
#learning-project-list thead .cell-wrap {
    background: #111827 !important;
    color: #FFFFFF !important;
}
#learning-project-list thead button,
#learning-project-list thead span {
    background: transparent !important;
    color: #FFFFFF !important;
}
#learning-project-list ::-webkit-scrollbar {width: 10px; height: 10px;}
#learning-project-list ::-webkit-scrollbar-thumb {background: #9CA3AF;}
#learning-roadmap-json .cm-editor {
    height: 360px !important;
    min-height: 360px !important;
    max-height: 360px !important;
}
#learning-roadmap-json .cm-scroller {
    overflow: auto !important;
    scrollbar-gutter: stable;
}
#learning-roadmap-json ::-webkit-scrollbar {width: 10px; height: 10px;}
#learning-roadmap-json ::-webkit-scrollbar-thumb {background: #9CA3AF;}

/* ===== 指标卡片 ===== */
.le-metric {
    display: inline-block;
    background: var(--le-card);
    border: 1px solid var(--le-border);
    border-radius: var(--le-radius);
    padding: 20px 28px;
    margin: 6px;
    text-align: center;
    box-shadow: var(--le-shadow);
    min-width: 120px;
}
.le-metric .val {
    font-size: 32px;
    font-weight: 800;
    color: var(--le-primary);
    display: block;
    line-height: 1.2;
}
.le-metric .lbl {
    font-size: 13px;
    color: var(--le-text-muted);
    margin-top: 6px;
}

/* ===== 标签页内的滚动 ===== */
.scrollable {max-height: calc(100vh - 70px) !important; overflow-y: auto !important;}

/* ===== 滚动条 ===== */
.gradio-container ::-webkit-scrollbar {width: 8px; height: 8px;}
.gradio-container ::-webkit-scrollbar-track {background: transparent;}
.gradio-container ::-webkit-scrollbar-thumb {background: #D1D5DB; border-radius: 4px;}
.gradio-container ::-webkit-scrollbar-thumb:hover {background: #9CA3AF;}

/* ===== 隐藏一些 Kotaemon 默认丑陋元素 ===== */
.gradio-container .tooltip {display: none !important;}

/* ===== 状态提示美化 ===== */
.gradio-container .prose p:first-child:empty {display: none;}
</style>
"""

V1_CSS = """
:root {
    --le-primary: #536F9D;
    --le-primary-light: #7E96BC;
    --le-primary-dark: #3E587F;
    --le-bg: #F7F8FA;
    --le-card: #FFFFFF;
    --le-border: #E5E7EB;
    --le-text: #1F2937;
    --le-text-muted: #6B7280;
    --le-selected: #EAF0F8;
    --le-success: #2F855A;
    --le-warning: #B7791F;
    --le-danger: #C53030;
    --le-shadow: 0 1px 3px rgba(31, 41, 55, .06), 0 1px 2px rgba(31, 41, 55, .04);
    --le-shadow-md: 0 4px 14px rgba(31, 41, 55, .10);
    --le-radius: 16px;
}

html, body, .gradio-container, .gradio-container * {
    font-family: -apple-system, BlinkMacSystemFont, "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif !important;
}
.gradio-container {
    background: var(--le-bg) !important;
    color: var(--le-text) !important;
}
.gradio-container .form,
.gradio-container .gr-block,
.gradio-container .gr-box,
.gradio-container .gradio-accordion,
.gradio-container .gr-form,
.gradio-container .wrap:not(.tab-nav):not(.gap) {
    border-color: var(--le-border) !important;
    background: var(--le-card) !important;
    border-radius: var(--le-radius) !important;
    box-shadow: var(--le-shadow) !important;
}
#learning-navigation {
    --le-sidebar-width: 220px;
    grid-template-columns: var(--le-sidebar-width) minmax(0, 1fr) !important;
    background: var(--le-bg) !important;
}
#learning-navigation > .tab-nav {
    padding: 60px 14px 20px !important;
    border-right: 1px solid var(--le-border) !important;
    box-shadow: var(--le-shadow) !important;
}
#learning-navigation > .tab-nav > button {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    min-height: 44px !important;
    padding: 10px 12px !important;
    border: 0 !important;
    border-radius: 10px !important;
    color: var(--le-text-muted) !important;
    font-size: 14px !important;
    font-weight: 600 !important;
}
#learning-navigation > .tab-nav > button:hover {
    color: var(--le-primary-dark) !important;
    background: var(--le-selected) !important;
}
#learning-navigation > .tab-nav > button.selected {
    color: var(--le-primary-dark) !important;
    background: var(--le-selected) !important;
    border-left: 0 !important;
}
.le-nav-icon {
    display: inline-flex;
    width: 20px;
    height: 20px;
    flex: 0 0 20px;
}
.le-nav-icon svg {width: 20px; height: 20px;}
#le-navigation-toggle {
    position: fixed !important;
    top: 14px !important;
    left: calc(var(--le-sidebar-width) - 48px) !important;
    bottom: auto !important;
    z-index: 50 !important;
    width: 36px !important;
    min-width: 36px !important;
    height: 36px !important;
    padding: 7px !important;
    border: 1px solid var(--le-border) !important;
    border-radius: 9px !important;
    background: var(--le-card) !important;
    color: var(--le-primary-dark) !important;
    box-shadow: var(--le-shadow) !important;
}
#le-navigation-toggle:hover {background: var(--le-selected) !important;}
#le-navigation-toggle svg {width: 20px; height: 20px; transform: none !important;}
#learning-navigation.le-sidebar-collapsed {
    grid-template-columns: 0 minmax(0, 1fr) !important;
}
#learning-navigation.le-sidebar-collapsed > .tab-nav {display: none !important;}
#learning-navigation.le-sidebar-collapsed > .tabitem {
    padding-left: 64px !important;
}
#learning-navigation.le-sidebar-collapsed #le-navigation-toggle {
    left: 14px !important;
}
#learning-navigation > .tabitem {
    min-width: 0 !important;
    max-width: none !important;
    padding: 24px 28px !important;
}
#learning-navigation > .tab-nav > button.le-nav-secondary:first-of-type {
    margin-top: auto !important;
}
.le-nav-label {min-width: 0; overflow: hidden; text-overflow: ellipsis;}
.gradio-container input[type="text"],
.gradio-container input[type="password"],
.gradio-container input[type="number"],
.gradio-container textarea,
.gradio-container select {
    border: 1px solid var(--le-border) !important;
    border-radius: 10px !important;
    background: #FFFFFF !important;
}
.gradio-container input:focus,
.gradio-container textarea:focus,
.gradio-container select:focus {
    border-color: var(--le-primary) !important;
    box-shadow: 0 0 0 3px rgba(83, 111, 157, .15) !important;
}
.gradio-container button.primary,
.gradio-container button[data-testid="submit-button"] {
    background: var(--le-primary) !important;
    border: 1px solid var(--le-primary) !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    color: #FFFFFF !important;
}
.gradio-container button.primary:hover {
    background: var(--le-primary-dark) !important;
    transform: none !important;
    box-shadow: var(--le-shadow) !important;
}
.gradio-container button:not(.primary):not([variant="stop"]):not(.tool):not(.icon-button) {
    border-radius: 10px !important;
    border-color: var(--le-border) !important;
    background: var(--le-card) !important;
    color: var(--le-text) !important;
}
.gradio-container button:not(.primary):not([variant="stop"]):not(.tool):not(.icon-button):hover {
    border-color: var(--le-primary) !important;
    color: var(--le-primary-dark) !important;
    background: var(--le-selected) !important;
}
.gradio-container button:focus-visible,
.gradio-container input:focus-visible,
.gradio-container textarea:focus-visible {
    outline: 2px solid var(--le-primary-light) !important;
    outline-offset: 2px;
}
.gradio-container h1, .gradio-container h2, .gradio-container h3 {
    color: var(--le-text) !important;
}
.gradio-container h1 {font-size: 24px !important; border-bottom: 0 !important;}
.gradio-container h2 {font-size: 20px !important; border-left: 0 !important; padding-left: 0 !important;}
.gradio-container blockquote {
    background: var(--le-selected) !important;
    border-left: 3px solid var(--le-primary) !important;
    color: var(--le-text) !important;
}
.gradio-container .prose, .gradio-container .md {
    color: var(--le-text) !important;
    line-height: 1.7 !important;
}
.gradio-container table thead,
.gradio-container table thead th {
    background: #111827 !important;
    color: #FFFFFF !important;
}
.gradio-container table tr:nth-child(even) {background: #F9FAFB !important;}
#learning-navigation > .tabitem.scrollable {
    height: 100vh !important;
    height: 100dvh !important;
    max-height: 100vh !important;
    max-height: 100dvh !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    overscroll-behavior: contain;
    scrollbar-gutter: stable;
}
#learning-navigation > #learning-course-tab,
#learning-navigation > #learning-review-tab {overflow: hidden !important;}
@media (max-width: 900px) {
    #learning-navigation {--le-sidebar-width: 184px;}
    #learning-navigation > .tabitem {padding: 18px !important;}
}
@media (max-width: 760px) {
    #learning-navigation > #learning-course-tab {overflow-y: auto !important;}
}
"""


V1_CSS += """
#le-back-to-top {
    position: fixed;
    right: 28px;
    bottom: 28px;
    z-index: 40;
    width: 38px;
    height: 38px;
    display: grid;
    place-items: center;
    padding: 8px;
    border: 1px solid #dce3ef;
    border-radius: 12px;
    color: #536fa0;
    background: #fff;
    box-shadow: 0 2px 8px #172b4d18;
    cursor: pointer;
}
#le-back-to-top[hidden] {display: none !important;}
#le-back-to-top:hover {background: #edf2fa;}
#le-back-to-top:focus-visible {outline: 2px solid #536fa0; outline-offset: 3px;}
#le-back-to-top svg {width: 100%; height: 100%;}
#learning-navigation > .tabitem {padding: 16px 20px !important;}
#learning-navigation > .tab-nav > button {padding: 10px 12px !important;}
#learning-home-tab h1, #learning-review-tab h1 {font-size: 22px !important;}
#learning-home-tab {max-width: 1400px !important;}
#learning-home-tab .form {padding: 8px !important;}
#le-course-layout, #le-course-catalog, #le-course-main {height: calc(100dvh - 32px) !important; min-height: 0 !important;}
#le-course-content {margin-top: 0 !important; padding: 16px 20px !important;}
#learning-navigation > #learning-review-tab {overflow: hidden !important;}
#le-review-layout {
    height: calc(100dvh - 32px);
    min-height: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    flex-wrap: nowrap !important;
    gap: 12px !important;
}
#le-review-body {
    flex: 1 1 0 !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    flex-wrap: nowrap !important;
    gap: 12px !important;
    padding: 2px 8px 16px 2px !important;
}
#le-review-body > * {flex-shrink: 0 !important;}
#le-review-body .form {padding: 8px !important;}
#le-review-body .prose p {margin: 6px 0 !important;}
#le-review-stats {gap: 16px !important;}
#le-review-actions {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    flex-wrap: nowrap !important;
    gap: 8px !important;
    padding: 10px 12px !important;
    background: var(--le-card);
    border: 1px solid var(--le-border);
    border-radius: 12px;
}
#le-review-actions > .row {flex-wrap: nowrap !important; gap: 8px !important;}
#le-review-actions button {min-width: 0 !important; padding: 8px 12px !important;}
#le-review-actions button:disabled {opacity: .5; cursor: not-allowed;}
#le-review-actions .prose {max-height: 60px; overflow-y: auto;}
"""


class LearningApp(KotaemonApp):

    """带学习特化功能的 Kotaemon App"""

    public_events = []

    def initialize_indices(self):
        from ktem.settings import BaseSettingGroup
        from learning_ext.index_manager import LearningIndexManager

        self.index_manager = LearningIndexManager(self)
        self.index_manager.on_application_startup()
        for index in self.index_manager.indices:
            self.default_settings.index.options[index.id] = BaseSettingGroup(
                settings=index.get_user_settings()
            )

    def __init__(self):
        getattr(flowsettings, "KH_MODE", "")
        flowsettings.KH_APP_NAME = APP_NAME
        flowsettings.KH_APP_VERSION = __version__
        super().__init__()
        try:
            from learning_ext.bootstrap import init_learning_ext

            init_learning_ext()
        except Exception as e:
            logger.warning(f"learning_ext 初始化延迟: {e} (将在首次使用时重试)")

    def make(self):
        markmap_js = """
        <script>
            window.markmap = {
                /** @type AutoLoaderOptions */
                autoLoader: {
                    toolbar: true, // Enable toolbar
                },
            };
        </script>
        """
        external_js = (
            "<script type='module' "
            "src='https://cdn.skypack.dev/pdfjs-viewer-element'>"
            "</script>"
            "<script type='module' "
            "src='https://cdnjs.cloudflare.com/ajax/libs/tributejs/5.1.3/tribute.min.js'>"
            f"{markmap_js}"
            "<script src='https://cdn.jsdelivr.net/npm/markmap-autoloader@0.16'></script>"
            "<script src='https://cdn.jsdelivr.net/npm/minisearch@7.1.1/dist/umd/index.min.js'></script>"
            "</script>"
            "<link rel='stylesheet' href='https://cdnjs.cloudflare.com/ajax/libs/tributejs/5.1.3/tribute.css'/>"
        )

        with gr.Blocks(
            theme=self._theme,
            css=(
                self._css
                + BEAUTIFY_CSS.replace("<style>", "").replace("</style>", "")
                + V1_CSS
            ),
            title=self.app_name,
            analytics_enabled=False,
            js=self._js,
            head=external_js,
        ) as demo:
            self.app = demo
            self.settings_state.render()
            self.user_id.render()

            self.ui()

            self.declare_public_events()
            self.subscribe_public_events()
            self.register_events()
            self.on_app_created()

            from learning_ext.localization import localize_pages

            demo.load(None, None, None, js=localize_pages(self))
            demo.load(None, None, None, js=self._pdf_view_js)
            demo.load(None, None, None, js=Path(__file__).with_name("assets").joinpath("course_catalog.js").read_text(encoding="utf-8"))
            demo.load(
                None, None, None,
                js=Path(__file__).with_name("assets").joinpath("navigation.js").read_text(encoding="utf-8"),
            )

        return demo

    def _build_quick_setup_tab(self, visible: bool):
        """极简模型配置页 (替换 Kotaemon 复杂的 Resources 页)"""
        from learning_ext.pages import QuickSetupPage

        with gr.Tab(
            "模型配置",
            elem_id="quick-setup-tab",
            id="quick-setup-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["quick-setup-tab"]:
            self.quick_setup_page = QuickSetupPage(self)
            self.quick_setup_page.on_building_ui()

    def _build_learning_tabs(self, visible: bool):
        from learning_ext.pages import (
            CourseCreatorPage,
            CourseManagementPage,
            CoursePage,
            QuizPage,
            ReviewPage,
        )
        from ktem.pages.chat import ChatPage

        self.learning_creator_page = CourseCreatorPage(self)
        with gr.Tab(
            "首页", elem_id="learning-home-tab", id="learning-home-tab",
            visible=visible, elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-home-tab"]:
            self.learning_creator_page.on_building_ui()

        self.learning_course_page = CoursePage(self)
        with gr.Tab(
            "我的课程",
            elem_id="learning-course-tab",
            id="learning-course-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-course-tab"]:
            self.learning_course_page.on_building_ui()

        self.learning_management_page = CourseManagementPage(self)
        with gr.Tab(
            "课程管理",
            elem_id="learning-management-tab",
            id="learning-management-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-management-tab"]:
            self.learning_management_page.on_building_ui()

        with gr.Tab(
            "知识问答",
            elem_id="chat-tab",
            id="chat-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["chat-tab"]:
            self.chat_page = ChatPage(self)

        with gr.Tab(
            "间隔复习",
            elem_id="learning-review-tab",
            id="learning-review-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-review-tab"]:
            self.learning_review_page = ReviewPage(self)
            self.learning_review_page.on_building_ui()

        with gr.Tab(
            "查漏测验",
            elem_id="learning-quiz-tab",
            id="learning-quiz-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-quiz-tab"]:
            self.learning_quiz_page = QuizPage(self)
            self.learning_quiz_page.on_building_ui()

    def _register_extra_events(self):
        for page_attr in (
            "quick_setup_page",
            "learning_creator_page",
            "learning_course_page",
            "learning_management_page",
            "learning_review_page",
            "learning_quiz_page",
        ):
            page = getattr(self, page_attr, None)
            if page is not None and hasattr(page, "on_register_events"):
                try:
                    page.on_register_events()
                except Exception as e:
                    logger.warning(f"{page_attr} 事件绑定失败: {e}")

    def ui(self):
        """重写 UI：精简 Tab 为中文 + 极简配置页替换复杂 Resources 页"""
        from ktem.pages.setup import SetupPage

        KH_ENABLE_FIRST_SETUP_local = getattr(
            flowsettings, "KH_ENABLE_FIRST_SETUP", False
        )
        KH_APP_DATA_EXISTS_local = getattr(flowsettings, "KH_APP_DATA_EXISTS", True)
        if config("KH_FIRST_SETUP", default=False, cast=bool):
            KH_APP_DATA_EXISTS_local = False

        self._tabs = {}

        with gr.Tabs(elem_id="learning-navigation", selected="learning-home-tab") as self.tabs:
            vis = True

            # 课程创建、学习与管理
            self._build_learning_tabs(visible=vis)

            # 资料库
            if len(self.index_manager.indices) == 1:
                for index in self.index_manager.indices:
                    with gr.Tab(
                        "资料库",
                        elem_id="indices-tab",
                        elem_classes=[
                            "fill-main-area-height",
                            "scrollable",
                            "indices-tab",
                        ],
                        id="indices-tab",
                        visible=vis and not KH_DEMO_MODE,
                    ) as self._tabs[f"{index.id}-tab"]:
                        setattr(self, f"_index_{index.id}", index.get_index_page_ui())
            elif len(self.index_manager.indices) > 1:
                with gr.Tab(
                    "资料库",
                    elem_id="indices-tab",
                    elem_classes=["fill-main-area-height", "scrollable", "indices-tab"],
                    id="indices-tab",
                    visible=vis and not KH_DEMO_MODE,
                ) as self._tabs["indices-tab"]:
                    for index in self.index_manager.indices:
                        with gr.Tab(
                            index.name, elem_id=f"{index.id}-tab"
                        ) as self._tabs[f"{index.id}-tab"]:
                            setattr(
                                self, f"_index_{index.id}", index.get_index_page_ui()
                            )
            # 下部导航入口
            self._build_quick_setup_tab(visible=vis)
            if KH_ENABLE_FIRST_SETUP_local:
                with gr.Column(visible=False) as self.setup_page_wrapper:
                    self.setup_page = SetupPage(self)

    def on_subscribe_public_events(self):
        super().on_subscribe_public_events()

    def on_register_events(self):
        super().on_register_events()
