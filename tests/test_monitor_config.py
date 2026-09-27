from pathlib import Path

from b2t.config import load_config


def test_load_config_with_monitor_section(tmp_path: Path) -> None:
    presets_path = tmp_path / "summary_presets.toml"
    presets_path.write_text(
        """
default = "basic"

[presets.basic]
label = "Basic"
prompt_template = "{content}"
""".strip(),
        encoding="utf-8",
    )

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[download]
output_dir = "./transcriptions"
db_dir = "./db"

[storage]
backend = "local"

[stt]
profile = "qwen"

[stt.profiles.qwen]
provider = "qwen"
language = "zh"

[summarize]
profile = "bailian-main"
preset = "basic"
presets_file = "{presets_path.name}"

[summarize.profiles.bailian-main]
provider = "bailian"
model = "qwen3-max"
api_key = ""

[fancy_html]
profile = "bailian-main"

[bilibili]
SESSDATA = "sess"
bili_jct = "csrf"
buvid3 = "buvid"
DedeUserID = "10001"
DedeUserID__ckMd5 = "md5"

[monitor]
enabled = true
state_file = "./state/monitor.json"
lookback_hours = 24
first_run_max_push = 2
default_check_interval = 180

[[monitor.creators]]
uid = 123456
name = "测试UP"
check_interval = 240
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.monitor.enabled is True
    # Legacy processing settings are accepted but no longer used.
    assert not hasattr(config.monitor, "lookback_hours")
    assert not hasattr(config.monitor, "first_run_max_push")
    assert config.monitor.creators[0].uid == 123456
    assert config.monitor.creators[0].check_interval == 240
    assert config.bilibili.SESSDATA == "sess"
    assert config.bilibili.DedeUserID == "10001"
    assert config.bilibili.credentials_file == str(
        tmp_path / "db_data" / "bilibili_credentials.json"
    )
    assert Path(config.monitor.state_file).is_absolute()
