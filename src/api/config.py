import os
import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(os.environ.get("OPENCOZMO_CONFIG", "config.yaml"))

DEFAULTS: dict = {
    "robot": {
        "wifi_ssid": "",  # Auto-detected if empty
        "connect_timeout_s": 10,
        "turn_calibration_factor": 2.11,  # Empirical correction for turn accuracy
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8765,
        "mdns_name": "opencozmo",
    },
    "camera": {
        "enabled": True,
        "fps": 15,
        "quality": 70,
    },
    "sensors": {
        "state_event_log_hz": 1.0,  # 1 log/s by default, <=0 disables periodic log
        "auto_broadcast_state": False,  # Auto-broadcast robotstate via websocket (if False, only on system.status request)
    },
    "llm": {
        "url": "https://api.mistral.ai/v1",
        "model": "mistral-small",
        "api_key": "",  # Override via env: OPENCOZMO_LLM_KEY
    },
    "logging": {
        "level": "INFO",
        "output_dir": "logs",  # Path where latest.log and last.log will be created
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides on top of the loaded config."""
    env_map = {
        "OPENCOZMO_LLM_KEY":      ("llm", "api_key"),
        "OPENCOZMO_LLM_URL":      ("llm", "url"),
        "OPENCOZMO_LLM_MODEL":    ("llm", "model"),
        "OPENCOZMO_SERVER_HOST":  ("server", "host"),
        "OPENCOZMO_SERVER_PORT":  ("server", "port"),
        "OPENCOZMO_STATE_LOG_HZ": ("sensors", "state_event_log_hz"),
        "OPENCOZMO_LOG_LEVEL":    ("logging", "level"),
        "OPENCOZMO_LOG_DIR":      ("logging", "output_dir"),
    }
    for env_var, (section, key) in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            config[section][key] = value
            logger.debug("Config override from env: %s → %s.%s", env_var, section, key)
    return config


def load() -> dict:
    """
    Load configuration from file, creating it with defaults if it doesn't exist.
    Environment variables are applied on top and always win.
    """
    if not CONFIG_PATH.exists():
        logger.warning("No config file found at '%s'. Creating one with defaults.", CONFIG_PATH)
        CONFIG_PATH.write_text(
            "# OpenCozmo API Configuration\n"
            "# Environment variables override any value here.\n"
            "# See ARCHITECTURE.md for the full reference.\n\n"
            + yaml.dump(DEFAULTS, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        config = DEFAULTS.copy()
    else:
        with CONFIG_PATH.open(encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        # Merge so any keys added in DEFAULTS but absent from the file still get their default
        config = _deep_merge(DEFAULTS, loaded)
        logger.info("Config loaded from '%s'.", CONFIG_PATH)

    config = _apply_env_overrides(config)
    return config
