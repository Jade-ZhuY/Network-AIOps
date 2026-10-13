"""Start the WebUI against the existing API without putting its key in argv."""

import os
import runpy
import sys
from pathlib import Path


def patch_download_script(script: str) -> str:
    """Retain upstream exports while adding state sync and a visible save link."""
    replacements = {
        "if (!runId || state.runId !== runId || state.pending.has(format)) return [skip(), skip(), skip()];": """if (!runId) return [skip(), skip(), skip()];
        if (state.runId !== runId) {
            state.pending.clear();
            state.runId = runId;
        }
        if (state.pending.has(format)) return [skip(), skip(), skip()];""",
        'const anchor = document.createElement("a");': """let downloadUrl;
        try {
            downloadUrl = new URL(file.url, window.location.href);
            if (downloadUrl.origin !== window.location.origin ||
                !downloadUrl.pathname.startsWith("/gradio_api/file=")) {
                throw new Error("unexpected download origin or route");
            }
        } catch (error) {
            return [button(label, true), '<div role="alert">下载地址异常，请刷新页面后重新转换。</div>'];
        }
        const anchor = document.createElement("a");""",
        "anchor.href = file.url;": "anchor.href = downloadUrl.href;",
        'return [button(label, true), ""];': """return [button(label, true),
            `<div role="status" data-mineru-download-ready="true">${escapeHtml(label)} 已准备好：
            <a href="${escapeHtml(downloadUrl.href)}" download="${escapeHtml(file.orig_name || "download")}">
            点击保存到电脑</a>（JSON / Markdown 下载包为 ZIP，解压后查看。）</div>`];""",
    }
    for original, replacement in replacements.items():
        if script.count(original) != 1:
            raise RuntimeError("MinerU download script differs from the verified 4.0.12 version")
        script = script.replace(original, replacement, 1)
    return script


def install_download_patch() -> None:
    """Patch only the known WebUI resource, without editing the shared image."""
    from importlib.metadata import version

    from mineru.kit.gradio import app as gradio_app

    if version("mineru") != "4.0.12":
        raise RuntimeError("The WebUI download patch requires MinerU 4.0.12")
    resource_text = gradio_app._resource_text
    script = patch_download_script(resource_text("gradio_download.js"))
    old_css = '.mineru-kit-download-notice:not(:has([role="alert"]))'
    if gradio_app._KIT_MENU_CSS.count(old_css) != 1:
        raise RuntimeError("MinerU download notice CSS differs from the verified version")
    gradio_app._KIT_MENU_CSS = gradio_app._KIT_MENU_CSS.replace(
        old_css, '.mineru-kit-download-notice:not(:has(a)):not(:has([role="alert"]))', 1
    )

    def patched_resource(name: str) -> str:
        return script if name == "gradio_download.js" else resource_text(name)

    gradio_app._resource_text = patched_resource


def launch_configuration(environment: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    key_path = Path(environment.get("MINERU_API_KEY_FILE", "/run/secrets/mineru_api_key"))
    key = key_path.read_text(encoding="utf-8").strip()
    if len(key) < 32 or not key.isascii() or any(char.isspace() for char in key):
        raise ValueError("Invalid MinerU API key file")
    api_url = environment.get("MINERU_API_URL", "http://api:8000")
    if not api_url.startswith("http://api:8000") or api_url.rstrip("/") != "http://api:8000":
        raise ValueError("WebUI must connect to the deployment's existing API")
    process_environment = {**environment, "MINERU_API_KEY": key}
    command = [
        "mineru-kit",
        "webui",
        "--api-url",
        "http://api:8000",
        "--server-name",
        "0.0.0.0",
        "--server-port",
        "7860",
        "--output-dir",
        "/data/output",
        "--no-enable-example",
    ]
    return command, process_environment


def main() -> None:
    command, environment = launch_configuration(dict(os.environ))
    for name in ("home", "tmp", "output"):
        Path("/data", name).mkdir(parents=True, exist_ok=True)
    install_download_patch()
    os.environ.update(environment)
    sys.argv = command
    runpy.run_module("mineru.kit.main", run_name="__main__")


if __name__ == "__main__":
    main()
