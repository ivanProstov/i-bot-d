"""Реестр плагинов. Код стратегии регистрируется только после записи в каталоге."""

from ibotd.plugins.ma_cross import MaCross

CATALOG = (
    {'id': 'ma-cross', 'name': 'Пересечение скользящих', 'implemented': True, 'where': 'раздел 4.3'},
    {'id': 'bollinger', 'name': 'Полосы Боллинджера', 'implemented': False, 'where': 'раздел 7.1'},
    {'id': 'bollinger-dump', 'name': 'Пролив от средней линии Боллинджера', 'implemented': False, 'where': 'раздел 7.2'},
)


class Registry:
    def __init__(self):
        self._by_id = {}

    def register(self, plugin):
        if plugin.id in self._by_id:
            raise ValueError(f'плагин {plugin.id} уже зарегистрирован')
        entry = next((item for item in CATALOG if item['id'] == plugin.id), None)
        if entry is None:
            raise ValueError('пока записи в каталоге нет, кода плагина нет')
        if not entry['implemented']:
            raise ValueError(f'плагин {plugin.id} в каталоге ещё не в поставке')
        self._by_id[plugin.id] = plugin
        return plugin

    def get(self, strategy_id):
        if not isinstance(strategy_id, str) or strategy_id not in self._by_id:
            raise ValueError('в реестре нет такого strategyId')
        return self._by_id[strategy_id]

    def ids(self):
        return tuple(self._by_id)


def _builtin():
    registry = Registry()
    registry.register(MaCross())
    return registry


REGISTRY = _builtin()


def get_plugin(strategy_id):
    return REGISTRY.get(strategy_id)


def param_labels(plugin):
    return {item['key']: item['label'] for item in plugin.params}


def grid_params(plugin):
    return {item['key']: item for item in plugin.params if item.get('grid')}


_PUBLIC_PARAM_KEYS = ('key', 'label', 'type', 'unit', 'default', 'grid', 'options', 'integer', 'min', 'hypothesis')


def public_view(plugin):
    params = []
    for item in plugin.params:
        params.append({key: item[key] for key in _PUBLIC_PARAM_KEYS if key in item})
    return {
        'id': plugin.id,
        'name': plugin.name,
        'rule': plugin.rule,
        'params': params,
        'seriesParams': list(plugin.series_params),
        'constraint': dict(plugin.constraint) if plugin.constraint else None,
    }


def public_plugins():
    return [public_view(plugin) for plugin in REGISTRY._by_id.values()]
