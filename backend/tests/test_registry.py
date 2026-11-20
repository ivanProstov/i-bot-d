import pytest

from ibotd.plugins.ma_cross import MaCross
from ibotd.registry import CATALOG, REGISTRY, Registry, get_plugin, public_plugins


def test_only_ma_cross_is_registered():
    assert [item['id'] for item in CATALOG] == ['ma-cross', 'bollinger', 'bollinger-dump']
    assert [item['implemented'] for item in CATALOG] == [True, False, False]
    assert REGISTRY.ids() == ('ma-cross',)
    plugin = get_plugin('ma-cross')
    assert plugin.id == 'ma-cross'
    assert public_plugins()[0]['id'] == 'ma-cross'
    assert public_plugins()[0]['constraint'] == {'left': 'fastPeriod', 'op': '<', 'right': 'slowPeriod'}
    grid = [item['key'] for item in public_plugins()[0]['params'] if item['grid']]
    assert 'leverage' not in grid
    assert 'orderNotional' not in grid
    assert 'fastPeriod' in grid
    with pytest.raises(ValueError, match='в реестре нет'):
        get_plugin('bollinger')
    with pytest.raises(ValueError, match='в реестре нет'):
        get_plugin('rsi')


def test_code_without_catalog_entry_is_refused():
    registry = Registry()

    class Other:
        id = 'not-in-catalog'

    with pytest.raises(ValueError, match='каталоге нет'):
        registry.register(Other())

    class Later:
        id = 'bollinger'

    with pytest.raises(ValueError, match='не в поставке'):
        registry.register(Later())

    registry.register(MaCross())
    with pytest.raises(ValueError, match='уже зарегистрирован'):
        registry.register(MaCross())
