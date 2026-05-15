import { useMemo } from 'react';
import type { HistoryItem, Mode } from '../types';

interface Props {
  history: HistoryItem[];
  modes: Mode[];
  onClear: () => void;
  onDelete: (id: string) => void;
  onToast: (msg: string) => void;
}

const CUSTOM_BADGE_COLORS = [
  { bg: 'rgba(255,92,0,.18)',   color: '#ff7a2f' },
  { bg: 'rgba(168,85,247,.18)', color: '#c084fc' },
  { bg: 'rgba(236,72,153,.18)', color: '#f472b6' },
  { bg: 'rgba(245,158,11,.18)', color: '#fbbf24' },
  { bg: 'rgba(20,184,166,.18)', color: '#2dd4bf' },
  { bg: 'rgba(99,102,241,.18)', color: '#818cf8' },
];

function formatTime(ts: number) {
  const d = new Date(ts);
  return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
}

function getDateLabel(ts: number): string {
  const now = new Date();
  const d = new Date(ts);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const itemDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());

  if (itemDay.getTime() === today.getTime()) return '今天';
  if (itemDay.getTime() === yesterday.getTime()) return '昨天';
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function groupByDate(items: HistoryItem[]) {
  const groups: { label: string; items: HistoryItem[] }[] = [];
  const seen = new Map<string, number>();

  for (const item of items) {
    const label = getDateLabel(item.timestamp);
    if (seen.has(label)) {
      groups[seen.get(label)!].items.push(item);
    } else {
      seen.set(label, groups.length);
      groups.push({ label, items: [item] });
    }
  }
  return groups;
}

const MODE_LABELS: Record<string, string> = {
  translate: '译',
  polish: '润',
  transcribe: '写',
};

function calcStats(history: HistoryItem[]) {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const monthItems = history.filter(h => h.timestamp >= monthStart);
  const charCount = monthItems.reduce((s, h) => s + h.text.length, 0);
  return { chars: charCount, total: history.length };
}

export function HistoryPage({ history, modes, onClear, onDelete, onToast }: Props) {
  const groups = groupByDate(history);
  const { chars, total } = calcStats(history);

  const customBadgeMap = useMemo(() => {
    const map: Record<string, { label: string; bg: string; color: string }> = {};
    modes.filter(m => m.isCustom).forEach((m, i) => {
      const c = CUSTOM_BADGE_COLORS[i % CUSTOM_BADGE_COLORS.length];
      map[m.id] = { label: m.name[0] ?? '?', bg: c.bg, color: c.color };
    });
    return map;
  }, [modes]);

  async function handleCopy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      onToast('已复制到剪贴板');
    } catch {
      onToast('复制失败');
    }
  }

  async function handleExport() {
    const lines = history.map(h => {
      const d = new Date(h.timestamp);
      const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${formatTime(h.timestamp)}`;
      if (h.originalText) {
        return `[${dateStr}] 原: ${h.originalText}\n[${dateStr}] →  ${h.text}`;
      }
      return `[${dateStr}] ${h.text}`;
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `shokztype-history-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    onToast('已导出');
  }

  if (history.length === 0) {
    return (
      <div className="history-page">
        <div className="page-header">
          <span className="page-title">历史记录</span>
          <button className="btn btn-ghost btn-sm" disabled>
            导出 ↑
          </button>
        </div>

        <div className="history-empty">
          <div className="history-empty-bg">S</div>
          <div className="history-empty-title">还没有转录记录</div>
          <div className="history-empty-sub">开始一次语音输入后，记录会出现在这里</div>
        </div>

        <div className="history-footer">
          <button className="btn btn-danger btn-sm" disabled>
            <span style={{ fontSize: 13 }}>🗑</span> 清空
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="history-page">
      <div className="page-header">
        <span className="page-title">历史记录</span>
        <button className="btn btn-ghost btn-sm" onClick={handleExport}>
          导出 ↑
        </button>
      </div>

      <div className="history-stats">
        <span className="history-stat-pill">本月 <strong>{chars.toLocaleString()}</strong> 字</span>
        <span className="history-stat-pill">共 <strong>{total}</strong> 条</span>
      </div>

      <div className="history-list">
        {groups.map(group => (
          <div key={group.label} className="history-date-group">
            <div className="history-date-label">{group.label}</div>
            {group.items.map(item => (
              <div key={item.id} className="history-item">
                <span className="history-item-time">{formatTime(item.timestamp)}</span>
                {MODE_LABELS[item.mode] ? (
                  <span className={`history-mode-badge mode-${item.mode}`}>{MODE_LABELS[item.mode]}</span>
                ) : customBadgeMap[item.mode] ? (
                  <span className="history-mode-badge" style={{ background: customBadgeMap[item.mode].bg, color: customBadgeMap[item.mode].color }}>
                    {customBadgeMap[item.mode].label}
                  </span>
                ) : null}
                {item.originalText ? (
                  <div className="history-item-comparison">
                    <span className="history-item-original">{item.originalText}</span>
                    <span className="history-item-text">{item.text}</span>
                  </div>
                ) : (
                  <span className="history-item-text">{item.text}</span>
                )}
                <div className="history-item-actions">
                  <button
                    className="btn btn-icon btn-sm"
                    onClick={() => handleCopy(item.text)}
                    title="复制"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <rect x="5" y="5" width="8" height="8" rx="1.5" />
                      <path d="M9 5V3a1 1 0 00-1-1H3a1 1 0 00-1 1v5a1 1 0 001 1h2" />
                    </svg>
                  </button>
                  <button
                    className="btn btn-icon btn-sm history-item-delete"
                    onClick={() => onDelete(item.id)}
                    title="删除"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M2 3.5h10M5.5 3.5V2.5a1 1 0 011-1h1a1 1 0 011 1v1M6 6.5v4M8 6.5v4M3 3.5l.7 7a1 1 0 001 .9h4.6a1 1 0 001-.9l.7-7" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="history-footer">
        <button
          className="btn btn-danger btn-sm"
          onClick={() => {
            if (confirm('确定清空所有历史记录？')) onClear();
          }}
        >
          <span style={{ fontSize: 13 }}>🗑</span> 清空
        </button>
      </div>
    </div>
  );
}
