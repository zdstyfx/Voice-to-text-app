import type { Page, Settings, WakeupConfig } from '../types';

interface Props {
  page: Page;
  onNavigate: (p: Page) => void;
  settings: Settings;
  wakeup: WakeupConfig;
}

function deriveStatus(settings: Settings) {
  const asrBackend = settings.asr?.backend ?? 'volcengine';
  const hasVolcKey = !!settings.cloud_asr?.volcengine?.api_key;
  const asr = asrBackend === 'local'
    ? { dot: 'ok', label: '本地运行中', cls: 'ok' }
    : hasVolcKey
      ? { dot: 'ok', label: '已配置', cls: 'ok' }
      : { dot: 'unconfigured', label: '未配置', cls: '' };

  const hasAI = !!(settings.llm?.apiKey && settings.llm?.apiBaseUrl);
  const ai = hasAI
    ? { dot: 'ok', label: '已连接', cls: 'ok' }
    : { dot: 'unconfigured', label: '未配置', cls: '' };

  return { asr, ai };
}

export function Sidebar({ page, onNavigate, settings, wakeup: _wakeup }: Props) {
  const { asr, ai } = deriveStatus(settings);

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-mark">S</div>
        <span className="logo-text">ShokzType</span>
      </div>

      <nav className="sidebar-nav">
        <button
          className={`nav-item${page === 'home' ? ' active' : ''}`}
          onClick={() => onNavigate('home')}
        >
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" style={{ flexShrink: 0 }}>
            <path d="M2 7.5L9 2l7 5.5V16a1 1 0 01-1 1H3a1 1 0 01-1-1V7.5z" />
            <path d="M6.5 17V11h5v6" />
          </svg>
          首页
        </button>

        <button
          className={`nav-item${page === 'history' ? ' active' : ''}`}
          onClick={() => onNavigate('history')}
        >
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" style={{ flexShrink: 0 }}>
            <circle cx="9" cy="9" r="7" />
            <path d="M9 5v4.5l3 1.5" strokeLinecap="round" />
          </svg>
          历史记录
        </button>

        <button
          className={`nav-item${page === 'settings' ? ' active' : ''}`}
          onClick={() => onNavigate('settings')}
        >
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" style={{ flexShrink: 0 }}>
            <circle cx="9" cy="9" r="2.5" />
            <path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.7 3.7l1.4 1.4M12.9 12.9l1.4 1.4M3.7 14.3l1.4-1.4M12.9 5.1l1.4-1.4" strokeLinecap="round" />
          </svg>
          设置
        </button>
      </nav>

      <div className="sidebar-status">
        <div className="status-row" onClick={() => onNavigate('settings')}>
          <span className="status-dot ok" />
          <span className="status-label">麦克风</span>
          <span className={`status-value ok`}>已连接</span>
          <span style={{ color: 'var(--ink4)', fontSize: 10, marginLeft: 2 }}>›</span>
        </div>
        <div className="status-row" onClick={() => onNavigate('settings')}>
          <span className={`status-dot ${asr.dot}`} />
          <span className="status-label">ASR 引擎</span>
          <span className={`status-value ${asr.cls}`}>{asr.label}</span>
          <span style={{ color: 'var(--ink4)', fontSize: 10, marginLeft: 2 }}>›</span>
        </div>
        <div className="status-row" onClick={() => onNavigate('settings')}>
          <span className={`status-dot ${ai.dot}`} />
          <span className="status-label">AI 服务</span>
          <span className={`status-value ${ai.cls}`}>{ai.label}</span>
          <span style={{ color: 'var(--ink4)', fontSize: 10, marginLeft: 2 }}>›</span>
        </div>
      </div>
    </aside>
  );
}

