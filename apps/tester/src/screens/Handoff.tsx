import { useEffect, useState } from 'react';
import { api } from '../api';
import { num } from '../format';

type Draft = {
  id: string;
  status: string;
  config: {
    strategyId: string;
    symbol: string;
    interval: string;
    market: string;
    runId: string;
    lotStep: number | null;
    params: Record<string, string | number | boolean>;
  };
  metrics: {
    Profit: number | null;
    ProfitFact: number | null;
    Winrate: number | null;
    Trades: number;
    MaxDraw: number | null;
    historyFrom: string;
    historyTo: string;
    earlyStopPct: number;
  };
};
type Book = { id: string; name: string; kind: string; band: string; created_at: string };

export function HandoffScreen() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [books, setBooks] = useState<Book[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void Promise.all([api<{ drafts: Draft[] }>('/api/drafts'), api<{ books: Book[] }>('/api/books')])
      .then(([draftBody, bookBody]) => {
        setDrafts(draftBody.drafts);
        setBooks(bookBody.books);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  return (
    <section>
      <h1>Передача в торговлю</h1>
      <p className="lead">
        Отмеченная строка становится черновиком конфига. Принять его может только программа торговли. Её в этом изменении нет, поэтому черновик остаётся черновиком.
      </p>
      {error ? <p className="error">{error}</p> : null}
      {drafts.length === 0 ? <p className="note">Черновиков нет.</p> : null}
      {drafts.map((draft) => (
        <article key={draft.id} className="card">
          <p>{draft.config.symbol} {draft.config.interval} · {draft.config.strategyId} · {draft.config.market} · {draft.status}</p>
          <p>
            Profit {num(draft.metrics.Profit)}, ProfitFact {num(draft.metrics.ProfitFact)}, Winrate {num(draft.metrics.Winrate)},
            сделок {draft.metrics.Trades}, MaxDraw {num(draft.metrics.MaxDraw)}.
          </p>
          <p className="note">
            История {draft.metrics.historyFrom} — {draft.metrics.historyTo}. Порог остановки {draft.metrics.earlyStopPct}%.
            Прогон {draft.config.runId}. Шаг лота {draft.config.lotStep ?? '—'}.
          </p>
          <p className="note">
            fast {String(draft.config.params.fastPeriod)} / slow {String(draft.config.params.slowPeriod)},
            offset {String(draft.config.params.offsetPct)}, lifetime {String(draft.config.params.lifetimeBars)},
            take {String(draft.config.params.takeProfitPct)}, stop {String(draft.config.params.stopLossPct)},
            {String(draft.config.params.direction)}, {String(draft.config.params.crossMode)}, {String(draft.config.params.exitMode)}.
            entryOnClose: {String(draft.config.params.entryOnClose)}.
          </p>
        </article>
      ))}
      <h2>Сводные</h2>
      <p className="note">Полные названия книг со схемы в спеке не записаны. Здесь два вида: исследовательская и рабочая, и две группы: короткие и старшие таймфреймы.</p>
      {books.length === 0 ? <p className="note">Сводных нет.</p> : null}
      {books.map((book) => (
        <p key={book.id}>
          {book.name} · {book.kind === 'working' ? 'рабочая' : 'исследовательская'} · {book.band === 'higher' ? 'старшие' : 'короткие'}
          {' '}
          <a href={`/api/books/${book.id}/export.xlsx`}>xlsx</a>
        </p>
      ))}
    </section>
  );
}
