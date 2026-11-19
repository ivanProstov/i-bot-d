import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { DataScreen } from './screens/Data';
import { GridScreen } from './screens/Grid';
import { HandoffScreen } from './screens/Handoff';
import { IdeaScreen } from './screens/Idea';
import { PlanScreen } from './screens/Plan';
import { RefineScreen } from './screens/Refine';
import { RunScreen } from './screens/Run';
import { TableScreen } from './screens/Table';

const links = [
  ['/idea', 'Идея'],
  ['/data', 'Данные'],
  ['/grid', 'Сетка'],
  ['/run', 'Прогон'],
  ['/table', 'Таблица'],
  ['/refine', 'Уточнение'],
  ['/plan', 'План гипотез'],
  ['/handoff', 'Передача'],
];

export function App() {
  return (
    <div className="app">
      <aside>
        <p className="brand">Тестировщик</p>
        <p className="brand-note">Binance USD-M. Ордера отсюда не отправляются.</p>
        <nav>
          {links.map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/idea" replace />} />
          <Route path="/idea" element={<IdeaScreen />} />
          <Route path="/data" element={<DataScreen />} />
          <Route path="/grid" element={<GridScreen />} />
          <Route path="/run" element={<RunScreen />} />
          <Route path="/table" element={<TableScreen />} />
          <Route path="/refine" element={<RefineScreen />} />
          <Route path="/plan" element={<PlanScreen />} />
          <Route path="/handoff" element={<HandoffScreen />} />
        </Routes>
      </main>
    </div>
  );
}
