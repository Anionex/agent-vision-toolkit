#!/usr/bin/env python3
"""Isolated, no-launchd installation test."""

import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import tempfile
import tomllib


def main():
    repo = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        home = root / "home"
        codex = home / ".codex"
        codex.mkdir(parents=True)
        (codex / "config.toml").write_text('personality = "friendly"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n')
        env_file = root / "test.env"
        env_file.write_text(
            "DEEPSEEK_API_KEY=test-deepseek\n"
            "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
            "UPSTREAM_MODEL=deepseek-v4-flash\n"
            "VISION_API_KEY=test-vision\n"
            "VISION_BASE_URL=https://vision.example/v1\n"
            "VISION_MODEL=test-vision-model\n"
            "PORT=19222\n"
            "MODEL_SLUG=deepseek-v4-flash-vision\n"
        )
        install_dir = home / ".local/share/codex-deepseek-vision"
        config_dir = home / ".config/codex-deepseek-vision"
        bin_dir = home / ".local/bin"
        plist = home / "Library/LaunchAgents/test.plist"
        environment = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex), ENV_SOURCE=str(env_file),
                           INSTALL_DIR=str(install_dir), CONFIG_DIR=str(config_dir),
                           BIN_DIR=str(bin_dir), PLIST=str(plist))
        command = [str(repo / "install.sh"), "--with-glance", "--no-start"]
        subprocess.run(command, cwd=repo, env=environment, check=True, capture_output=True, text=True)
        catalog_path = codex / "cc-switch-model-catalog.json"
        incomplete = json.loads(catalog_path.read_text())
        incomplete["models"][0].pop("input_modalities")
        catalog_path.write_text(json.dumps(incomplete))
        subprocess.run(command + ["--inject-reasoning-summary"], cwd=repo, env=environment,
                       check=True, capture_output=True, text=True)

        config = tomllib.loads((codex / "config.toml").read_text())
        assert config["model"] == "deepseek-v4-flash-vision"
        assert config["model_providers"]["deepseek_vision"]["base_url"] == "http://127.0.0.1:19222"
        catalog = json.loads((codex / "cc-switch-model-catalog.json").read_text())
        models = [item for item in catalog["models"] if item["slug"] == "deepseek-v4-flash-vision"]
        assert len(models) == 1
        assert models[0]["display_name"] == "DeepSeek V4 Flash"
        assert "image" in models[0]["input_modalities"]
        assert models[0]["supports_reasoning_summaries"] is True
        installed_env = config_dir / "env"
        assert stat.S_IMODE(installed_env.stat().st_mode) == 0o600
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        plist_data = plistlib.loads(plist.read_bytes())
        plist_text = repr(plist_data)
        assert "test-deepseek" not in plist_text and "test-vision" not in plist_text
        subprocess.run([str(bin_dir / "glance"), "--help"], env=environment,
                       check=True, capture_output=True, text=True)
        uninstall_env = dict(environment, NO_LAUNCHCTL="1")
        subprocess.run([str(repo / "uninstall.sh")], cwd=repo, env=uninstall_env,
                       check=True, capture_output=True, text=True)
        assert not install_dir.exists()
        assert not (bin_dir / "glance").exists()
        assert not plist.exists()
        assert installed_env.exists(), "uninstall must preserve local secrets"

        bin_dir.mkdir(parents=True, exist_ok=True)
        foreign = bin_dir / "glance"
        foreign.write_text("#!/bin/sh\necho foreign\n")
        failed = subprocess.run(command, cwd=repo, env=environment, capture_output=True, text=True)
        assert failed.returncode != 0
        assert foreign.read_text() == "#!/bin/sh\necho foreign\n"
        assert not install_dir.exists(), "glance conflict must be detected before installation"
    print("INSTALL TEST PASS")


if __name__ == "__main__":
    main()
