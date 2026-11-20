"""Общий пакет тестировщика и будущей торговли.

Контракт конфига, строка результата, гипотезы, реестр плагинов, модуль Binance USD-M
и формулы прогона живут здесь, чтобы обе программы считали одно и то же.
"""

from ibotd.contract import build_bot_config, metrics_snapshot, normalize_params
from ibotd.registry import CATALOG, get_plugin, public_plugins

__all__ = [
    'CATALOG',
    'build_bot_config',
    'get_plugin',
    'metrics_snapshot',
    'normalize_params',
    'public_plugins',
]
