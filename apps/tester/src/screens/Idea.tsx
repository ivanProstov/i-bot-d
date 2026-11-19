import { useEffect, useState } from 'react';
import { api } from '../api';
import { loadCatalog, type CatalogItem } from '../catalog';
import { loadWorkspace, saveWorkspace } from '../workspace';

type Idea = { id: string; name: string; ruleText: string; strategyId: string };

export function IdeaScreen() {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [name, setName] = useState('');
  const [ruleText, setRuleText] = useState('');
  const [strategyId, setStrategyId] = useState('ma-cross');
  const [currentId, setCurrentId] = useState<string | null>(loadWorkspace().ideaId);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');

  async function reload() {
    const body = await api<{ ideas: Idea[] }>('/api/ideas');
    setIdeas(body.ideas);
  }

  useEffect(() => {
    void reload().catch((reason: Error) => setError(reason.message));
    void loadCatalog().then((body) => setCatalog(body.catalog)).catch((reason: Error) => setError(reason.message));
  }, []);

  function edit(idea: Idea) {
    setCurrentId(idea.id);
    setName(idea.name);
    setRuleText(idea.ruleText);
    setStrategyId(idea.strategyId);
    saveWorkspace({ ideaId: idea.id });
    setSaved('');
  }

  async function save() {
    setError('');
    setSaved('');
    try {
      const body = { name, ruleText, strategyId };
      const idea = currentId
        ? await api<Idea>(`/api/ideas/${currentId}`, { method: 'PUT', body: JSON.stringify(body) })
        : await api<Idea>('/api/ideas', { method: 'POST', body: JSON.stringify(body) });
      setCurrentId(idea.id);
      saveWorkspace({ ideaId: idea.id });
      setSaved('Идея записана. Дальше — экран «Данные».');
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return (
    <section>
      <h1>Идея</h1>
      <p className="lead">Имя, правило своими словами и плагин из реестра. Список строится из каталога. Плагина без записи в каталоге здесь нет.</p>
      <div className="stack">
        <label>
          Имя
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Правило своими словами
          <textarea value={ruleText} onChange={(event) => setRuleText(event.target.value)} />
        </label>
        <label>
          Плагин
          <select value={strategyId} onChange={(event) => setStrategyId(event.target.value)}>
            {catalog.map((item) => (
              <option key={item.id} value={item.id} disabled={!item.implemented}>
                {item.name}
                {item.implemented ? '' : ' — не в первой поставке'}
              </option>
            ))}
          </select>
        </label>
        <div className="row">
          <button onClick={() => void save()}>{currentId ? 'Обновить идею' : 'Записать идею'}</button>
          <button
            className="secondary"
            onClick={() => {
              setCurrentId(null);
              setName('');
              setRuleText('');
              setStrategyId('ma-cross');
              setSaved('');
            }}
          >
            Новая
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {saved ? <p className="ok">{saved}</p> : null}
      </div>
      <h2>Записанные идеи</h2>
      {ideas.length === 0 ? <p className="note">Пока пусто.</p> : null}
      {ideas.map((idea) => (
        <button key={idea.id} className="card secondary" onClick={() => edit(idea)}>
          {idea.name} · {idea.strategyId}
          {idea.id === currentId ? ' · текущая' : ''}
        </button>
      ))}
    </section>
  );
}
