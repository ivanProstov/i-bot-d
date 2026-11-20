export type Workspace = {
  ideaId: string | null;
  seriesId: string | null;
  from: string;
  to: string;
  runId: string | null;
  selectedRowIds: string[];
};

export type GridDraft = {
  numbers: Record<string, { from: string; to: string; step: string }>;
  enums: Record<string, string[]>;
  deposit: string;
  earlyStopPct: string;
  orderNotional: string;
  leverage: string;
  constraintEnabled: boolean;
  workers?: string;
};

const workspaceKey = 'tester.workspace';
const gridKey = 'tester.grid';

const emptyWorkspace: Workspace = {
  ideaId: null,
  seriesId: null,
  from: '',
  to: '',
  runId: null,
  selectedRowIds: [],
};

export function loadWorkspace(): Workspace {
  try {
    const raw = sessionStorage.getItem(workspaceKey);
    if (!raw) return { ...emptyWorkspace };
    return { ...emptyWorkspace, ...JSON.parse(raw) };
  } catch {
    return { ...emptyWorkspace };
  }
}

export function saveWorkspace(patch: Partial<Workspace>): Workspace {
  const next = { ...loadWorkspace(), ...patch };
  sessionStorage.setItem(workspaceKey, JSON.stringify(next));
  return next;
}

export function loadGrid(): GridDraft | null {
  try {
    const raw = sessionStorage.getItem(gridKey);
    return raw ? (JSON.parse(raw) as GridDraft) : null;
  } catch {
    return null;
  }
}

export function saveGrid(draft: GridDraft): void {
  sessionStorage.setItem(gridKey, JSON.stringify(draft));
}
