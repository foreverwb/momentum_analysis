const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

export const BEIJING_TIMEZONE = 'Asia/Shanghai';

const BEIJING_DATE_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: BEIJING_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const BEIJING_DATETIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: BEIJING_TIMEZONE,
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export const normalizeUtcTimestamp = (value?: string | null): string | null => {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(trimmed)) {
    return `${trimmed}Z`;
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(trimmed)) {
    return `${trimmed.replace(' ', 'T')}Z`;
  }
  return trimmed;
};

export const parseUtcTimestampMs = (value?: string | null): number => {
  const normalized = normalizeUtcTimestamp(value);
  if (!normalized) return Number.NaN;
  return new Date(normalized).getTime();
};

export const getBeijingCutoffBoundaryMs = (nowMs: number, cutoffHour = 8): number => {
  const beijingNow = new Date(nowMs + BEIJING_OFFSET_MS);
  const year = beijingNow.getUTCFullYear();
  const month = beijingNow.getUTCMonth();
  const day = beijingNow.getUTCDate();
  const hour = beijingNow.getUTCHours();
  let boundaryUtcMs = Date.UTC(year, month, day, cutoffHour - 8, 0, 0, 0);
  if (hour < cutoffHour) {
    boundaryUtcMs -= ONE_DAY_MS;
  }
  return boundaryUtcMs;
};

export const getBeijingBoundaryDateKey = (boundaryUtcMs: number): string => {
  const beijingBoundary = new Date(boundaryUtcMs + BEIJING_OFFSET_MS);
  const year = beijingBoundary.getUTCFullYear();
  const month = `${beijingBoundary.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${beijingBoundary.getUTCDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

export const getBeijingSyncWindowKey = (nowMs: number, cutoffHour = 8): string =>
  getBeijingBoundaryDateKey(getBeijingCutoffBoundaryMs(nowMs, cutoffHour));

export const formatBeijingBoundaryLabel = (boundaryUtcMs: number, cutoffHour = 8): string => {
  const beijingBoundary = new Date(boundaryUtcMs + BEIJING_OFFSET_MS);
  const year = beijingBoundary.getUTCFullYear();
  const month = `${beijingBoundary.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${beijingBoundary.getUTCDate()}`.padStart(2, '0');
  const hour = `${cutoffHour}`.padStart(2, '0');
  return `${year}-${month}-${day} ${hour}:00`;
};

export const formatDateInBeijing = (value?: string | null): string => {
  const normalized = normalizeUtcTimestamp(value);
  if (!normalized) return '--';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return '--';
  const parts = BEIJING_DATE_FORMATTER.formatToParts(date);
  const year = parts.find((part) => part.type === 'year')?.value ?? '----';
  const month = parts.find((part) => part.type === 'month')?.value ?? '--';
  const day = parts.find((part) => part.type === 'day')?.value ?? '--';
  return `${year}-${month}-${day}`;
};

export const formatDateTimeInBeijing = (value?: string | null): string => {
  const normalized = normalizeUtcTimestamp(value);
  if (!normalized) return '--';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return '--';
  const parts = BEIJING_DATETIME_FORMATTER.formatToParts(date);
  const month = parts.find((part) => part.type === 'month')?.value ?? '--';
  const day = parts.find((part) => part.type === 'day')?.value ?? '--';
  const hour = parts.find((part) => part.type === 'hour')?.value ?? '--';
  const minute = parts.find((part) => part.type === 'minute')?.value ?? '--';
  return `${month}-${day} ${hour}:${minute}`;
};
