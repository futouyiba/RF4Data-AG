from .base import InputDriver

__all__ = ["InputDriver"]


def get_software_driver(*args, **kwargs):
    """延迟导入 SoftwareInputDriver（避免在 pyautogui 未安装时崩溃）。"""
    from .software import SoftwareInputDriver
    return SoftwareInputDriver(*args, **kwargs)
