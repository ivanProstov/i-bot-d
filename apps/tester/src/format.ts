export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(value);
}

export function int(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value);
}

export function minutesText(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return 'нет оценки';
  if (minutes < 1) return 'меньше минуты';
  const total = Math.round(minutes);
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const rest = total % 60;
  if (days > 0) return `${days} д ${hours} ч`;
  if (hours > 0) return `${hours} ч ${rest} мин`;
  return `${rest} мин`;
}
