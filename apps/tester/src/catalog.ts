import { api } from './api';

export type Axis =
  | { key: string; kind: 'enum'; values: string[] }
  | { key: string; kind: 'number'; from: number; to: number; step: number };

export type PluginParam = {
  key: string;
  label: string;
  type: string;
  unit?: string;
  default: string | number | boolean;
  grid: boolean;
  options?: string[];
};

export type Plugin = {
  id: string;
  name: string;
  params: PluginParam[];
};

export type CatalogItem = {
  id: string;
  name: string;
  implemented: boolean;
};

export type Catalog = {
  catalog: CatalogItem[];
  plugins: Plugin[];
  intervals: string[];
};

export type Preset = {
  numbers: Record<string, { from: string; to: string; step: string }>;
  enums: Record<string, string[]>;
  note: Record<string, string>;
};

let catalogRequest: Promise<Catalog> | null = null;

export function loadCatalog(): Promise<Catalog> {
  catalogRequest ||= api<Catalog>('/api/catalog');
  return catalogRequest;
}

export function maPlugin(catalog: Catalog): Plugin {
  const plugin = catalog.plugins.find((item) => item.id === 'ma-cross');
  if (!plugin) throw new Error('плагин ma-cross не зарегистрирован');
  return plugin;
}
