"""只读静态预检；没有代码执行、依赖安装或预览供应商调用。"""
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import PurePosixPath

from services.workspace_generation import MAX_CONTEXT_CHARS, MAX_FILES, validate_file_path

BLOCK_REASON = "当前项目未接入经过验证的隔离运行服务；资源配额、超时终止、临时空间、网络控制及预览访问授权尚无可用保证，禁止构建或运行生成代码。"
ALLOWED_PACKAGES = {"react", "react-dom", "vite", "typescript", "@vitejs/plugin-react", "@vitejs/plugin-react-swc", "@types/react", "@types/react-dom"}
ALLOWED_SCRIPTS = {"dev": "vite", "build": "vite build", "preview": "vite preview"}


class EntryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries = []
        self.external = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            src = attrs.get("src", "")
            if src.startswith(("http:", "https:", "//", "data:", "blob:")):
                self.external = True
            elif attrs.get("type") == "module" and src:
                self.entries.append(src)


def preflight(files):
    issues = []
    def issue(code, message):
        issues.append({"code": code, "message": message})

    contents = {}
    for file in files:
        path, content = file["path"], file["content"]
        try:
            validate_file_path(path)
        except ValueError:
            issue("unsafe_path", "数据库中存在不允许的文件路径或类型，预检拒绝该项目。")
            continue
        if path.lower() in {name.lower() for name in contents}:
            issue("duplicate_path", "数据库文件路径重复或大小写冲突。")
        contents[path] = content
    if not files:
        issue("empty_project", "项目没有已保存文件，请先生成应用代码。")
    if len(files) > MAX_FILES or sum(len(file["content"]) for file in files) > MAX_CONTEXT_CHARS:
        issue("source_limit", "项目超过预检限制：最多80个文件、200000字符。")
    entries = []
    if "index.html" not in contents:
        issue("missing_html", "缺少根目录 index.html，无法确认 React/Vite 页面入口。")
    elif len(contents["index.html"]) <= MAX_CONTEXT_CHARS:
        parser = EntryParser()
        try:
            parser.feed(contents["index.html"])
        except Exception:
            issue("invalid_html", "无法解析 index.html 的入口结构。")
        if parser.external:
            issue("external_entry", "入口引用外部脚本，未满足受控网络要求。")
        for reference in parser.entries:
            path = reference[1:] if reference.startswith("/") else reference.removeprefix("./")
            try:
                validate_file_path(path)
            except ValueError:
                issue("unsafe_entry", "HTML模块入口路径不符合安全约束。")
                continue
            if PurePosixPath(path).suffix not in {".ts", ".tsx", ".js", ".jsx"}:
                issue("invalid_entry_type", "模块入口必须是 JS 或 TS 源文件。")
            elif path not in contents:
                issue("missing_module", "HTML引用的模块入口文件未保存到数据库。")
            else:
                entries.append(path)
        if not parser.entries:
            issue("missing_module", "index.html 缺少本地 module 脚本入口。")
    manifest = contents.get("package.json")
    dependencies = []
    if manifest is None:
        issue("missing_manifest", "缺少 package.json，不能确认依赖清单。")
    elif len(manifest) > 20000:
        issue("manifest_limit", "package.json 超过20000字符限制。")
    else:
        try:
            data = json.loads(manifest)
            if not isinstance(data, dict):
                raise ValueError()
            if any(key in data for key in ("workspaces", "overrides", "resolutions", "pnpm")):
                issue("manifest_policy", "本轮预检不接受工作空间、依赖覆盖或包管理器扩展配置。")
            scripts = data.get("scripts", {})
            if not isinstance(scripts, dict) or any(ALLOWED_SCRIPTS.get(key) != value for key, value in scripts.items()):
                issue("unsafe_scripts", "仅允许固定 vite / vite build / vite preview 命令；生命周期脚本及自定义命令被拒绝。")
            for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
                packages = data.get(section, {})
                if not isinstance(packages, dict):
                    raise ValueError()
                for name, version in packages.items():
                    if name not in ALLOWED_PACKAGES or not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
                        issue("dependency_policy", "依赖必须位于 React/Vite 最小白名单且固定为精确版本；URL、Git、本地路径和版本范围均被拒绝。")
                    else:
                        dependencies.append({"name": name, "version": version})
            required = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if not {"react", "react-dom", "vite"}.issubset(required):
                issue("missing_dependency", "清单必须包含 react、react-dom 和 vite。")
        except (ValueError, TypeError, RecursionError):
            issue("invalid_manifest", "package.json 不是有效的受支持依赖清单。")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "status": "blocked", "can_run": False, "preview_url": None,
        "reason": BLOCK_REASON, "build_status": "not_started", "run_status": "not_started",
        "source": {"file_count": len(files), "revision": digest, "entry_paths": entries},
        "preflight": {"status": "issues_found" if issues else "passed_static_checks", "issues": issues, "dependencies": dependencies, "note": "只检查入口存在、路径及依赖清单，不编译代码；通过不代表可构建、代码安全或功能正确。"},
        "runtime": {"provider": None, "isolation": "unverified", "cpu_limit": None, "memory_limit_mb": None, "timeout_seconds": None, "network_policy": "unverified", "access_authorization": "unverified", "temporary_space": "unverified"},
        "logs": [], "logs_note": "没有构建或运行任务，因此没有真实运行日志。",
    }
