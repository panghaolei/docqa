"""配置包：集中管理测试工程的运行参数。"""

from conf.settings import Config, PROJECT_ROOT, load_config, resolve_base_url

__all__ = ["Config", "PROJECT_ROOT", "load_config", "resolve_base_url"]
