import { useState, useEffect, useRef } from 'react';
import type { Settings, Device, WakeupConfig, VoiceprintData, VoiceprintProfile, SettingsTab, LocalAsrStatus, Mode } from '../types';
import { api } from '../api';
import { EnrollModal } from './EnrollModal';

interface Props {
  settings: Settings;
  devices: Device[];
  wakeup: WakeupConfig;
  voiceprint: VoiceprintData;
  modes: Mode[];
  onSettings: (s: Settings) => void;
  onWakeup: (w: WakeupConfig) => void;
  onVoiceprint: (v: VoiceprintData) => void;
  onCreateCustomMode: (name: string, prompt: string) => Promise<{ success: boolean; error?: string }>;
  onUpdateModePrompt: (id: string, prompt: string) => Promise<void>;
  onUpdateModeDescription: (id: string, description: string) => Promise<void>;
  onDeleteCustomMode: (id: string) => Promise<void>;
  onToast: (msg: string) => void;
}

// ─── Toggle component ────────────────────────────────────────────────────────
function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="toggle-switch">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="toggle-track" />
    </label>
  );
}

// ─── Eye button ──────────────────────────────────────────────────────────────
function EyeBtn({ show, onToggle }: { show: boolean; onToggle: () => void }) {
  return (
    <button className="eye-btn" type="button" onClick={onToggle} tabIndex={-1}>
      {show ? '🙈' : '👁'}
    </button>
  );
}

// ─── Mic Tab ─────────────────────────────────────────────────────────────────
function MicTab({ settings, devices, onSettings, onToast }: Pick<Props, 'settings' | 'devices' | 'onSettings' | 'onToast'>) {
  const currentDevice = settings.audio?.device ?? '';

  async function handleDeviceChange(id: string) {
    const next = { audio: { ...settings.audio, device: id } };
    await api.saveSettings(next);
    onSettings({ ...settings, ...next });
    onToast('麦克风已更新');
  }

  return (
    <div>
      <div className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-title">音频设备</span>
        </div>
        <div style={{ padding: '14px 16px' }}>
          <div className="device-select-row">
            <span className="field-label">当前麦克风</span>
            <select
              value={currentDevice}
              onChange={e => handleDeviceChange(e.target.value)}
              style={{ flex: 1 }}
            >
              <option value="">默认设备</option>
              {devices.map(d => (
                <option key={d.id} value={d.id}>
                  {d.name}{d.is_default ? ' (默认)' : ''}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Wakeup Tab ──────────────────────────────────────────────────────────────
function WakeupTab({ wakeup, onWakeup, onToast }: Pick<Props, 'wakeup' | 'onWakeup' | 'onToast'>) {
  const [recordingKey, setRecordingKey] = useState(false);
  const [newStartKw, setNewStartKw] = useState('');
  const [addingStartKw, setAddingStartKw] = useState(false);
  const [newEndKw, setNewEndKw] = useState('');
  const [addingEndKw, setAddingEndKw] = useState(false);
  const [recordingUndoKey, setRecordingUndoKey] = useState(false);
  const [cmdInputs, setCmdInputs] = useState<Record<string, string>>({ undo: '', newline: '', enter: '' });
  const [addingCmdAction, setAddingCmdAction] = useState<string | null>(null);

  const methods = wakeup.methods ?? ['hotkey'];
  const hasHotkey = methods.includes('hotkey');
  const hasVad = methods.includes('vad');

  async function toggleMethod(method: string, enabled: boolean) {
    let next = enabled ? [...methods, method] : methods.filter(m => m !== method);
    if (next.length === 0) next = [method === 'hotkey' ? 'vad' : 'hotkey'];
    const res = await api.saveWakeup({ methods: next });
    if (res?.success === false) {
      onToast(res.error ?? '设置失败');
      return;
    }
    onWakeup({ ...wakeup, methods: next });
  }

  async function handleRecordHotkey() {
    setRecordingKey(true);
    try {
      const res = await api.recordHotkey();
      if (res.success) {
        await api.saveWakeup({ hotkey_combo: res.combo });
        onWakeup({ ...wakeup, hotkey_combo: res.combo });
        onToast('热键已更新为 ' + res.combo);
      }
    } finally {
      setRecordingKey(false);
    }
  }

  async function handleAddStartKeyword() {
    const kw = newStartKw.trim();
    if (!kw) return;
    setAddingStartKw(true);
    try {
      const res = await api.addStartKeyword(kw);
      if (res.success) {
        onWakeup({ ...wakeup, start_keywords: [...wakeup.start_keywords, kw] });
        setNewStartKw('');
        onToast('已添加唤醒词');
      } else {
        onToast(res.error ?? '添加失败');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : '添加失败');
    } finally {
      setAddingStartKw(false);
    }
  }

  async function handleDeleteStartKeyword(name: string) {
    await api.deleteStartKeyword(name);
    onWakeup({ ...wakeup, start_keywords: wakeup.start_keywords.filter(k => k !== name) });
  }

  async function handleAddEndKeyword() {
    const kw = newEndKw.trim();
    if (!kw) return;
    setAddingEndKw(true);
    try {
      const res = await api.addEndKeyword(kw);
      if (res.success) {
        onWakeup({ ...wakeup, end_keywords: [...(wakeup.end_keywords ?? []), kw] });
        setNewEndKw('');
        onToast('已添加结束词');
      } else {
        onToast(res.error ?? '添加失败');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : '添加失败');
    } finally {
      setAddingEndKw(false);
    }
  }

  async function handleDeleteEndKeyword(name: string) {
    await api.deleteEndKeyword(name);
    onWakeup({ ...wakeup, end_keywords: (wakeup.end_keywords ?? []).filter(k => k !== name) });
  }

  async function handleRecordUndoHotkey() {
    setRecordingUndoKey(true);
    try {
      const res = await api.recordHotkey();
      if (res.success) {
        await api.saveUndoHotkey(res.combo);
        onWakeup({ ...wakeup, undo_hotkey: res.combo });
        onToast('撤销快捷键已更新为 ' + res.combo);
      }
    } finally {
      setRecordingUndoKey(false);
    }
  }

  async function handleAddCmdKeyword(action: string) {
    const kw = (cmdInputs[action] ?? '').trim();
    if (!kw) return;
    setAddingCmdAction(action);
    try {
      const res = await api.addCommandKeyword(kw, action);
      if (res.success) {
        onWakeup({ ...wakeup, command_keywords: { ...(wakeup.command_keywords ?? {}), [kw]: action } });
        setCmdInputs(prev => ({ ...prev, [action]: '' }));
        onToast('已添加语音命令');
      } else {
        onToast(res.error ?? '添加失败');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : '添加失败');
    } finally {
      setAddingCmdAction(null);
    }
  }

  async function handleDeleteCmdKeyword(name: string) {
    await api.deleteCommandKeyword(name);
    const next = { ...(wakeup.command_keywords ?? {}) };
    delete next[name];
    onWakeup({ ...wakeup, command_keywords: next });
  }

  return (
    <div>
      <div className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-title">唤醒方式</span>
        </div>

        <div className="wakeup-method-row">
          <div className="wakeup-method-info">
            <div className="wakeup-method-name">热键唤醒</div>
            <div className="wakeup-method-desc">按住快捷键录音</div>
          </div>
          <Toggle checked={hasHotkey} onChange={v => toggleMethod('hotkey', v)} />
        </div>

        {hasHotkey && (
          <div className="wakeup-method-row" style={{ paddingTop: 8, paddingBottom: 12, background: 'var(--surface)' }}>
            <span style={{ flex: 1, fontSize: 13, color: 'var(--ink3)' }}>快捷键</span>
            <span
              className={`hotkey-chip${recordingKey ? ' recording' : ''}`}
              onClick={handleRecordHotkey}
              title="点击录制新热键"
            >
              {recordingKey ? '等待按键...' : (wakeup.hotkey_combo?.toUpperCase() ?? 'F9')}
            </span>
          </div>
        )}

        <div className="wakeup-method-row">
          <div className="wakeup-method-info">
            <div className="wakeup-method-name">语音唤醒</div>
            <div className="wakeup-method-desc">说出关键词开始录音</div>
          </div>
          <Toggle checked={hasVad} onChange={v => toggleMethod('vad', v)} />
        </div>
      </div>

      {hasVad && (
        <>
          <div className="settings-card">
            <div className="settings-card-header">
              <span className="settings-card-title">唤醒词</span>
              <span className="settings-card-subtitle">说出唤醒词开始录音</span>
            </div>
            <div className="keywords-list">
              {wakeup.start_keywords.length === 0 && (
                <span style={{ fontSize: 13, color: 'var(--ink4)' }}>暂无唤醒词</span>
              )}
              {wakeup.start_keywords.map(kw => (
                <span key={kw} className="keyword-chip">
                  {kw}
                  <button className="keyword-chip-del" onClick={() => handleDeleteStartKeyword(kw)}>×</button>
                </span>
              ))}
            </div>
            <div className="keyword-add-row">
              <input
                type="text"
                placeholder="输入唤醒词..."
                value={newStartKw}
                onChange={e => setNewStartKw(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddStartKeyword()}
              />
              <button
                className="btn btn-primary btn-sm"
                onClick={handleAddStartKeyword}
                disabled={addingStartKw || !newStartKw.trim()}
              >
                添加
              </button>
            </div>
          </div>

          <div className="settings-card">
            <div className="settings-card-header">
              <span className="settings-card-title">结束词</span>
              <span className="settings-card-subtitle">说出结束词停止录音</span>
            </div>
            <div className="keywords-list">
              {(wakeup.end_keywords ?? []).length === 0 && (
                <span style={{ fontSize: 13, color: 'var(--ink4)' }}>暂无结束词</span>
              )}
              {(wakeup.end_keywords ?? []).map(kw => (
                <span key={kw} className="keyword-chip">
                  {kw}
                  <button className="keyword-chip-del" onClick={() => handleDeleteEndKeyword(kw)}>×</button>
                </span>
              ))}
            </div>
            <div className="keyword-add-row">
              <input
                type="text"
                placeholder="输入结束词..."
                value={newEndKw}
                onChange={e => setNewEndKw(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddEndKeyword()}
              />
              <button
                className="btn btn-primary btn-sm"
                onClick={handleAddEndKeyword}
                disabled={addingEndKw || !newEndKw.trim()}
              >
                添加
              </button>
            </div>
          </div>
        </>
      )}

      {(() => {
        const cmdKws = wakeup.command_keywords ?? {};
        const cards = [
          { action: 'undo',    title: '撤销',  subtitle: '删除上一次输出' },
          { action: 'newline', title: '换行',  subtitle: 'Shift+Enter，不提交' },
          { action: 'enter',   title: '按回车', subtitle: 'Enter，发送命令' },
        ];
        return (
          <div style={{ display: 'flex', gap: 12 }}>
            {cards.map(({ action, title, subtitle }) => {
              const keywords = Object.entries(cmdKws).filter(([, a]) => a === action).map(([kw]) => kw);
              const inputVal = cmdInputs[action] ?? '';
              const isAdding = addingCmdAction === action;
              return (
                <div key={action} className="settings-card" style={{ flex: 1, minWidth: 0 }}>
                  <div className="settings-card-header">
                    <span className="settings-card-title">{title}</span>
                    <span className="settings-card-subtitle">{subtitle}</span>
                  </div>

                  {action === 'undo' && (
                    <div className="wakeup-method-row" style={{ paddingTop: 8, paddingBottom: 10 }}>
                      <span style={{ flex: 1, fontSize: 12, color: 'var(--ink3)' }}>快捷键</span>
                      <span
                        className={`hotkey-chip${recordingUndoKey ? ' recording' : ''}`}
                        onClick={handleRecordUndoHotkey}
                        title="点击录制"
                        style={{ fontSize: 11 }}
                      >
                        {recordingUndoKey ? '等待...' : (wakeup.undo_hotkey?.toUpperCase() ?? 'CTRL+SHIFT+Z')}
                      </span>
                    </div>
                  )}

                  <div className="keywords-list" style={{ minHeight: 32 }}>
                    {keywords.length === 0 && (
                      <span style={{ fontSize: 12, color: 'var(--ink4)' }}>暂无</span>
                    )}
                    {keywords.map(kw => (
                      <span key={kw} className="keyword-chip">
                        {kw}
                        <button className="keyword-chip-del" onClick={() => handleDeleteCmdKeyword(kw)}>×</button>
                      </span>
                    ))}
                  </div>

                  <div className="keyword-add-row" style={{ marginTop: 8 }}>
                    <input
                      type="text"
                      placeholder="添加词..."
                      value={inputVal}
                      onChange={e => setCmdInputs(prev => ({ ...prev, [action]: e.target.value }))}
                      onKeyDown={e => e.key === 'Enter' && handleAddCmdKeyword(action)}
                      style={{ fontSize: 12 }}
                    />
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => handleAddCmdKeyword(action)}
                      disabled={isAdding || !inputVal.trim()}
                    >
                      +
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}
    </div>
  );
}

// ─── ASR + LLM Service Tab ────────────────────────────────────────────────────
function AsrTab({ settings, onSettings, onToast }: Pick<Props, 'settings' | 'onSettings' | 'onToast'>) {
  // ASR state
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localKey, setLocalKey] = useState(settings.cloud_asr?.volcengine?.api_key ?? '');
  const [localModel, setLocalModel] = useState(settings.cloud_asr?.volcengine?.model_id ?? '');

  // LLM state
  const llm = settings.llm ?? { apiBaseUrl: '', apiKey: '', model: '', timeoutSeconds: 90, temperature: 0.2 };
  const [llmForm, setLlmForm] = useState({ ...llm });
  const [showLlmKey, setShowLlmKey] = useState(false);
  const [savingLlm, setSavingLlm] = useState(false);
  const [testingLlm, setTestingLlm] = useState(false);
  const [testStatus, setTestStatus] = useState<'ok' | 'error' | null>(null);
  const [showGuide, setShowGuide] = useState(false);
  const [guideProvider, setGuideProvider] = useState('volcengine');

  function setLlmField<K extends keyof typeof llmForm>(k: K, v: typeof llmForm[K]) {
    setLlmForm(f => ({ ...f, [k]: v }));
  }

  async function handleSaveLlm() {
    setSavingLlm(true);
    setTestStatus(null);
    try {
      await api.saveSettings({ llm: { ...llmForm } });
      onSettings({ ...settings, llm: { ...llmForm } });
      onToast('AI 服务设置已保存');
    } finally {
      setSavingLlm(false);
    }
  }

  async function handleTestLlm() {
    setTestingLlm(true);
    setTestStatus(null);
    try {
      await api.saveSettings({ llm: { ...llmForm } });
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: '测试', mode: 'polish' }),
      });
      const data = await res.json();
      setTestStatus(data.used_llm ? 'ok' : 'error');
    } catch {
      setTestStatus('error');
    } finally {
      setTestingLlm(false);
    }
  }

  const activeProviderData = AI_PROVIDERS.find(p => p.id === guideProvider)!;

  // Local model download state
  const [localStatus, setLocalStatus] = useState<LocalAsrStatus | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [dlProgress, setDlProgress] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  const currentBackend = settings.asr?.backend ?? 'volcengine';
  const hasKey = !!localKey.trim();

  useEffect(() => {
    api.getLocalAsrStatus().then(setLocalStatus).catch(() => {});
  }, []);

  useEffect(() => {
    return () => { esRef.current?.close(); };
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      const next: Partial<Settings> = {
        cloud_asr: { volcengine: { api_key: localKey, model_id: localModel } },
        asr: { ...settings.asr, backend: 'volcengine' },
      };
      await api.saveSettings(next);
      onSettings({ ...settings, ...next });
      onToast('火山引擎设置已保存');
    } finally {
      setSaving(false);
    }
  }

  async function handleStartDownload() {
    const res = await api.startLocalAsrDownload();
    if (!res.success) { onToast(res.message ?? '下载启动失败'); return; }
    setDownloading(true);
    setDlProgress(0);
    const es = new EventSource('/api/asr/local/download/stream');
    esRef.current = es;
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.overall_progress !== undefined) setDlProgress(data.overall_progress);
        if (data.stage === 'completed') {
          setDownloading(false);
          setDlProgress(100);
          es.close();
          setLocalStatus(s => s ? { ...s, downloaded: true, downloading: false } : s);
          onToast('本地模型下载完成');
        } else if (data.stage === 'error') {
          setDownloading(false);
          es.close();
          onToast('下载失败: ' + (data.error ?? '未知错误'));
        }
      } catch { /* ignore */ }
    };
  }

  async function handleSwitchToLocal() {
    const next: Partial<Settings> = { asr: { ...settings.asr, backend: 'local' } };
    await api.saveSettings(next);
    onSettings({ ...settings, ...next });
    onToast('已切换到本地离线模型');
  }

  async function handleSwitchToCloud() {
    const next: Partial<Settings> = { asr: { ...settings.asr, backend: 'volcengine' } };
    await api.saveSettings(next);
    onSettings({ ...settings, ...next });
    onToast('已切换到火山引擎云端识别');
  }

  const isLocalReady = localStatus?.downloaded ?? false;
  const isLocalActive = currentBackend === 'local';

  return (
    <div>
      {/* ── Cloud ASR (primary) ── */}
      <div className={`settings-card asr-card${currentBackend === 'volcengine' ? ' asr-card-active' : ''}`}>
        <div className="settings-card-header">
          <span className="settings-card-title">
            <span className="asr-card-badge cloud">推荐</span>
            火山引擎云端识别
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {currentBackend === 'volcengine' && (
              <span className="asr-active-chip">当前使用</span>
            )}
            <span className={`status-dot ${hasKey ? 'ok' : 'unconfigured'}`} />
            <span style={{ fontSize: 12, color: hasKey ? 'var(--green)' : 'var(--ink3)' }}>
              {hasKey ? '已配置' : '未配置'}
            </span>
            {isLocalActive && (
              <button className="btn btn-secondary btn-sm" onClick={handleSwitchToCloud}>
                切换到云端
              </button>
            )}
            <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
          </span>
        </div>

        <div style={{ padding: '4px 16px 14px' }}>
          <div className="field-row">
            <span className="field-label">API 密钥</span>
            <div className="field-input-wrap">
              <input
                type={showKey ? 'text' : 'password'}
                className="has-eye"
                placeholder="your-api-key"
                value={localKey}
                onChange={e => setLocalKey(e.target.value)}
              />
              <EyeBtn show={showKey} onToggle={() => setShowKey(v => !v)} />
            </div>
          </div>
          <div className="field-row">
            <span className="field-label">资源 ID<span className="field-label-optional">（可选）</span></span>
            <div className="field-input-wrap">
              <input
                type="text"
                placeholder="volc.bigasr.sauc.duration"
                value={localModel}
                onChange={e => setLocalModel(e.target.value)}
              />
              <span className="field-hint">留空则使用默认资源，通常无需填写</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Local model (optional) ── */}
      <div className={`settings-card asr-card${isLocalActive ? ' asr-card-active' : ''}`}>
        <div className="settings-card-header">
          <span className="settings-card-title">
            <span className="asr-card-badge local">离线</span>
            本地模型（FunASR）
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {isLocalActive && <span className="asr-active-chip">当前使用</span>}
            <span className={`status-dot ${isLocalReady ? 'ok' : 'unconfigured'}`} />
            <span style={{ fontSize: 12, color: isLocalReady ? 'var(--green)' : 'var(--ink3)' }}>
              {isLocalReady ? '已就绪' : '未下载'}
            </span>
          </span>
        </div>

        <div className="asr-local-body">
          <div className="asr-local-desc">
            无需网络，约 500 MB，识别结果不出境
          </div>

          {!isLocalReady && !downloading && (
            <button className="btn btn-secondary btn-sm" onClick={handleStartDownload}>
              ↓ 下载本地模型
            </button>
          )}

          {downloading && (
            <div className="asr-dl-wrap">
              <div className="asr-dl-bar-track">
                <div className="asr-dl-bar-fill" style={{ width: `${dlProgress}%` }} />
              </div>
              <span className="asr-dl-pct">{Math.round(dlProgress)}%</span>
            </div>
          )}

          {isLocalReady && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 13, color: 'var(--green)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <circle cx="7" cy="7" r="6" fill="var(--green)" opacity=".2"/>
                  <path d="M4 7l2 2 4-4" stroke="var(--green)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                可用
              </span>
              {!isLocalActive && (
                <button className="btn btn-secondary btn-sm" onClick={handleSwitchToLocal}>
                  切换到本地
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── LLM API section ── */}
      <div className="settings-card" style={{ marginTop: 20 }}>
        <div className="settings-card-header">
          <span style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span className="settings-card-title">AI 服务</span>
            <span className="settings-card-subtitle">翻译 / 润色 / 自定义模式使用</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {testStatus === 'ok' && <span style={{ fontSize: 12, color: 'var(--green)' }}>✓ 连接正常</span>}
            {testStatus === 'error' && <span style={{ fontSize: 12, color: 'var(--red)' }}>✗ 连接失败</span>}
            <button className="btn btn-secondary btn-sm" onClick={handleTestLlm} disabled={testingLlm}>
              {testingLlm ? '测试中...' : '测试连接'}
            </button>
            <button className="btn btn-primary btn-sm" onClick={handleSaveLlm} disabled={savingLlm}>
              {savingLlm ? '保存中...' : '保存'}
            </button>
          </span>
        </div>

        <button
          className="guide-toggle-btn guide-toggle-incard"
          type="button"
          onClick={() => setShowGuide(v => !v)}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            如何配置 AI 服务
            <span className="help-bubble" onClick={e => e.stopPropagation()}>
              ?
              <div className="help-tooltip">
                <div className="help-tooltip-title">为什么要配置 AI 服务？</div>
                <p>翻译和润色功能由 AI 大模型驱动。填入自己的 API 密钥，可以：</p>
                <ul>
                  <li><b>自由选择模型</b> — 字节豆包擅长中文语境，GPT-4o 综合能力更强，DeepSeek 性价比高</li>
                  <li><b>按用量付费</b> — 轻度使用时远比包月订阅便宜</li>
                  <li><b>数据更可控</b> — 语音内容直接发往你指定的服务商</li>
                </ul>
              </div>
            </span>
          </span>
          <span className="guide-toggle-arrow">{showGuide ? '▲' : '▼'}</span>
        </button>

        {showGuide && (
          <div className="ai-guide-panel ai-guide-incard">
            <div className="ai-guide-tabs">
              {AI_PROVIDERS.map(p => (
                <button
                  key={p.id}
                  className={`ai-guide-tab${guideProvider === p.id ? ' active' : ''}`}
                  onClick={() => setGuideProvider(p.id)}
                >{p.name}</button>
              ))}
            </div>
            <div className="ai-guide-body">
              <div className="ai-guide-row">
                <span className="ai-guide-key">接口地址</span>
                <code className="ai-guide-val">{activeProviderData.url}</code>
                <button className="ai-guide-fill-btn" onClick={() => setLlmField('apiBaseUrl', activeProviderData.url)}>填入</button>
              </div>
              <div className="ai-guide-row">
                <span className="ai-guide-key">密钥</span>
                <span className="ai-guide-desc">{activeProviderData.keyHint}</span>
              </div>
              <div className="ai-guide-row">
                <span className="ai-guide-key">模型</span>
                <span className="ai-guide-desc">{activeProviderData.modelHint}</span>
              </div>
            </div>
          </div>
        )}

        <div className="field-group field-group-incard">
          <div className="field-row">
            <span className="field-label">API 接口地址</span>
            <div className="field-input-wrap">
              <input type="text" placeholder="https://ark.cn-beijing.volces.com/api/v3"
                value={llmForm.apiBaseUrl} onChange={e => setLlmField('apiBaseUrl', e.target.value)} />
              <span className="field-hint">兼容 OpenAI 格式，不含 /chat/completions</span>
            </div>
          </div>
          <div className="field-row">
            <span className="field-label">API 密钥</span>
            <div className="field-input-wrap">
              <input type={showLlmKey ? 'text' : 'password'} className="has-eye"
                placeholder="ark-xxxx 或 sk-xxxx"
                value={llmForm.apiKey} onChange={e => setLlmField('apiKey', e.target.value)} />
              <EyeBtn show={showLlmKey} onToggle={() => setShowLlmKey(v => !v)} />
            </div>
          </div>
          <div className="field-row">
            <span className="field-label">接入点 / 模型 ID</span>
            <div className="field-input-wrap">
              <input type="text" placeholder="ep-xxxxxxxxxx-xxxxx 或 gpt-4o"
                value={llmForm.model} onChange={e => setLlmField('model', e.target.value)} />
              <span className="field-hint">字节方舟填接入点 ID（ep- 开头）；其他厂商填模型名</span>
            </div>
          </div>
          <div className="field-row">
            <span className="field-label">最长等待（秒）</span>
            <div className="field-input-wrap" style={{ maxWidth: 100 }}>
              <input type="number" min={5} max={300}
                value={llmForm.timeoutSeconds} onChange={e => setLlmField('timeoutSeconds', Number(e.target.value))} />
            </div>
          </div>
          <div className="field-row">
            <span className="field-label">回复稳定性</span>
            <div className="field-input-wrap">
              <input type="range" min={0} max={1} step={0.05}
                value={1 - llmForm.temperature}
                onChange={e => setLlmField('temperature', Number((1 - Number(e.target.value)).toFixed(2)))} />
              <div className="slider-labels"><span>稳定</span><span>多样</span></div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

// ─── Mode Tab ─────────────────────────────────────────────────────────────────
const LANG_OPTIONS = ['英语', '中文', '日语', '韩语', '法语', '德语', '西班牙语'];

const DEFAULT_PROMPTS = {
  translate: '#Role\n你是一个语音转写文本的翻译工具。\n\n#核心规则\n1. 翻译为{targetLanguage}\n2. 直接返回译文\n\n#输入\n{text}',
  polish: '#Role\n你是一个文本整理专家。\n\n#核心规则\n1. 将口语转为书面表达\n2. 直接返回整理后的文本\n\n#输入\n{text}',
};

const AI_PROVIDERS = [
  {
    id: 'volcengine',
    name: '字节方舟',
    url: 'https://ark.cn-beijing.volces.com/api/v3',
    keyHint: 'ark-xxxx-xxxx 格式，在控制台 → 密钥管理 中生成',
    modelHint: 'ep-xxxxxxxxxx-xxxxx，在控制台 → 接入点管理 中复制',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    url: 'https://api.openai.com/v1',
    keyHint: 'sk-xxxx 格式，在 platform.openai.com → API Keys 中生成',
    modelHint: 'gpt-4o · gpt-4o-mini · gpt-4-turbo 等',
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    url: 'https://api.deepseek.com',
    keyHint: 'sk-xxxx 格式，在 platform.deepseek.com → API Keys 中生成',
    modelHint: 'deepseek-chat · deepseek-reasoner',
  },
  {
    id: 'aliyun',
    name: '阿里百炼',
    url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    keyHint: 'sk-xxxx 格式，在百炼控制台 → API-KEY 管理 中生成',
    modelHint: 'qwen-plus · qwen-turbo · qwen-max 等',
  },
];

const EMAIL_TEMPLATE = '# 示例 Prompt（可直接修改）\n你是语音转写纠错专家。修正以下语音识别文字中的错误（同音字误识、断句不自然等），保持原意，只输出修正后的文字：\n\n{text}';

function AiTab({ settings, onSettings, onToast, modes, wakeup, onWakeup, onCreateCustomMode, onDeleteCustomMode, onUpdateModeDescription }: Pick<Props, 'settings' | 'onSettings' | 'onToast' | 'modes' | 'wakeup' | 'onWakeup' | 'onCreateCustomMode' | 'onDeleteCustomMode' | 'onUpdateModeDescription'>) {
  const [localLang, setLocalLang] = useState(settings.translateTargetLanguage ?? '英语');
  const [creatingMode, setCreatingMode] = useState(false);
  const [newModeName, setNewModeName] = useState('');
  const [newModePrompt, setNewModePrompt] = useState('');
  const [savingMode, setSavingMode] = useState(false);
  const [switchInputs, setSwitchInputs] = useState<Record<string, string>>({});
  const [addingSwitchAction, setAddingSwitchAction] = useState<string | null>(null);
  const [descriptions, setDescriptions] = useState<Record<string, string>>(() =>
    Object.fromEntries(modes.map(m => [m.id, m.description ?? '']))
  );
  useEffect(() => {
    setDescriptions(prev => {
      const next = { ...prev };
      // Add newly appeared modes; remove deleted ones; never overwrite existing local edits
      modes.forEach(m => { if (!(m.id in next)) next[m.id] = m.description ?? ''; });
      Object.keys(next).forEach(id => { if (!modes.find(m => m.id === id)) delete next[id]; });
      return next;
    });
  }, [modes]);
  const [prompts, setPrompts] = useState<Record<string, string>>(() => {
    const p: Record<string, string> = {
      translate: settings.prompts?.translate ?? DEFAULT_PROMPTS.translate,
      polish: settings.prompts?.polish ?? DEFAULT_PROMPTS.polish,
    };
    modes.filter(m => m.isCustom).forEach(m => {
      p[m.id] = settings.prompts?.[m.id] ?? m.prompt ?? '';
    });
    return p;
  });

  useEffect(() => {
    const p: Record<string, string> = {
      translate: settings.prompts?.translate ?? DEFAULT_PROMPTS.translate,
      polish: settings.prompts?.polish ?? DEFAULT_PROMPTS.polish,
    };
    modes.filter(m => m.isCustom).forEach(m => {
      p[m.id] = settings.prompts?.[m.id] ?? m.prompt ?? '';
    });
    setPrompts(p);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.prompts, modes]);

  const [savingCards, setSavingCards] = useState<Record<string, boolean>>({});

  async function handleSaveCard(modeId: string) {
    setSavingCards(prev => ({ ...prev, [modeId]: true }));
    try {
      const promptValue = prompts[modeId] ?? '';
      const extra: Partial<Settings> = modeId === 'translate' ? { translateTargetLanguage: localLang } : {};
      await api.saveSettings({ prompts: { [modeId]: promptValue }, ...extra });
      onSettings({ ...settings, prompts: { ...settings.prompts, [modeId]: promptValue }, ...extra });
      onToast('已保存');
    } finally {
      setSavingCards(prev => ({ ...prev, [modeId]: false }));
    }
  }

  async function handleAddSwitchKeyword(modeId: string) {
    const kw = (switchInputs[modeId] ?? '').trim();
    if (!kw) return;
    setAddingSwitchAction(modeId);
    try {
      const res = await api.addCommandKeyword(kw, `switch_mode:${modeId}`);
      if (res.success) {
        onWakeup({ ...wakeup, command_keywords: { ...(wakeup.command_keywords ?? {}), [kw]: `switch_mode:${modeId}` } });
        setSwitchInputs(prev => ({ ...prev, [modeId]: '' }));
        onToast('已添加切换口令');
      } else {
        onToast(res.error ?? '添加失败');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : '添加失败');
    } finally {
      setAddingSwitchAction(null);
    }
  }

  async function handleDeleteSwitchKeyword(keyword: string) {
    await api.deleteCommandKeyword(keyword);
    const next = { ...(wakeup.command_keywords ?? {}) };
    delete next[keyword];
    onWakeup({ ...wakeup, command_keywords: next });
  }

  async function handleCreateMode() {
    const name = newModeName.trim();
    if (!name) return;
    setSavingMode(true);
    try {
      const res = await onCreateCustomMode(name, newModePrompt.trim());
      if (res.success) {
        onToast('已创建模式');
        setCreatingMode(false);
        setNewModeName('');
        setNewModePrompt('');
      } else {
        onToast(res.error ?? '创建失败');
      }
    } finally {
      setSavingMode(false);
    }
  }

  return (
    <div>
      {modes.map(m => {
        const switchKws = Object.entries(wakeup.command_keywords ?? {})
          .filter(([, a]) => a === `switch_mode:${m.id}`)
          .map(([kw]) => kw);
        const switchInput = switchInputs[m.id] ?? '';
        const isAddingSw = addingSwitchAction === m.id;
        return (
          <div key={m.id} className="settings-card">
            {/* Header: title + desc | save + delete */}
            <div className="settings-card-header">
              <span style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                <span className="settings-card-title">{m.name}</span>
                <input
                  className="mode-desc-input"
                  value={descriptions[m.id] ?? ''}
                  placeholder="添加简短描述..."
                  onChange={e => setDescriptions(prev => ({ ...prev, [m.id]: e.target.value }))}
                  onBlur={e => {
                    const val = e.target.value.trim();
                    if (val !== (m.description ?? '')) onUpdateModeDescription(m.id, val);
                  }}
                />
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                {m.isCustom && (
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ color: 'var(--red)' }}
                    onClick={() => onDeleteCustomMode(m.id)}
                  >删除</button>
                )}
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => handleSaveCard(m.id)}
                  disabled={savingCards[m.id]}
                >{savingCards[m.id] ? '保存中...' : '保存'}</button>
              </span>
            </div>

            <div style={{ padding: '8px 16px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              {/* Switch keywords — own row */}
              <div className="mode-switch-row">
                <span style={{ fontSize: 12, color: 'var(--ink4)', whiteSpace: 'nowrap' }}>切换口令</span>
                {switchKws.map(kw => (
                  <span key={kw} className="keyword-chip">
                    {kw}
                    <button className="keyword-chip-del" onClick={() => handleDeleteSwitchKeyword(kw)}>×</button>
                  </span>
                ))}
                <input
                  type="text"
                  placeholder="添加口令..."
                  value={switchInput}
                  onChange={e => setSwitchInputs(prev => ({ ...prev, [m.id]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleAddSwitchKeyword(m.id)}
                  style={{ fontSize: 12, width: 80, flexShrink: 0 }}
                />
                <button
                  className={`mode-add-kw-btn${switchInput.trim() ? ' active' : ''}`}
                  onClick={() => handleAddSwitchKeyword(m.id)}
                  disabled={isAddingSw}
                >+</button>
              </div>

              {/* Target language — only for translate */}
              {m.id === 'translate' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 12, color: 'var(--ink4)', whiteSpace: 'nowrap' }}>目标语言</span>
                  <select value={localLang} onChange={e => setLocalLang(e.target.value)} style={{ flex: 1 }}>
                    {LANG_OPTIONS.map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
              )}

              {/* Prompt textarea */}
              {m.id !== 'transcribe' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, color: 'var(--ink4)' }}>
                      AI 指令
                      {m.id === 'translate'
                        ? <span style={{ marginLeft: 6, color: 'var(--ink5)' }}>变量：{'{text}'} {'{targetLanguage}'}</span>
                        : <span style={{ marginLeft: 6, color: 'var(--ink5)' }}>变量：{'{text}'}</span>
                      }
                    </span>
                    {!m.isCustom && (
                      <button
                        className="btn btn-ghost btn-sm"
                        type="button"
                        onClick={() => setPrompts(p => ({ ...p, [m.id]: DEFAULT_PROMPTS[m.id as keyof typeof DEFAULT_PROMPTS] }))}
                      >恢复默认</button>
                    )}
                  </div>
                  <textarea
                    className="prompt-textarea"
                    rows={5}
                    value={prompts[m.id] ?? ''}
                    onChange={e => setPrompts(p => ({ ...p, [m.id]: e.target.value }))}
                    spellCheck={false}
                  />
                </div>
              )}
            </div>
          </div>
        );
      })}

      {creatingMode ? (
        <div className="settings-card">
          <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input
              className="mode-edit-input"
              placeholder="模式名称"
              value={newModeName}
              onChange={e => setNewModeName(e.target.value)}
              autoFocus
            />
            <textarea
              className="prompt-textarea"
              rows={5}
              placeholder="AI 指令，用 {text} 代表转写内容..."
              value={newModePrompt}
              onChange={e => setNewModePrompt(e.target.value)}
              spellCheck={false}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setCreatingMode(false)}>取消</button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleCreateMode}
                disabled={savingMode || !newModeName.trim()}
              >{savingMode ? '创建中...' : '创建'}</button>
            </div>
          </div>
        </div>
      ) : (
        <button
          className="btn btn-ghost btn-sm"
          type="button"
          style={{ color: 'var(--accent)', marginTop: 4 }}
          onClick={() => { setCreatingMode(true); setNewModeName(''); setNewModePrompt(EMAIL_TEMPLATE); }}
        >+ 新建自定义模式</button>
      )}

    </div>
  );
}

// ─── Voiceprint Tab ───────────────────────────────────────────────────────────
const VP_COLORS = ['#FF5C00', '#22C55E', '#3B82F6', '#A855F7', '#F59E0B', '#EC4899'];

function VoiceprintTab({ voiceprint, onVoiceprint, onToast }: Pick<Props, 'voiceprint' | 'onVoiceprint' | 'onToast'>) {
  const [enrollTarget, setEnrollTarget] = useState<{ id: string; step: number } | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);
  const [newName, setNewName] = useState('');

  async function handleToggle(enabled: boolean) {
    const res = await api.toggleVoiceprint();
    if (!res.success && res.error) { onToast(res.error); return; }
    onVoiceprint({ ...voiceprint, enabled: res.enabled ?? enabled });
  }

  async function handleProfileClick(profile: VoiceprintProfile) {
    if (!profile.enrollment_complete) {
      setEnrollTarget({ id: profile.id, step: profile.enrollment_steps });
      return;
    }
    const isActive = voiceprint.activeProfiles.includes(profile.id);
    const next = isActive
      ? voiceprint.activeProfiles.filter(id => id !== profile.id)
      : [...voiceprint.activeProfiles, profile.id];
    const res = await api.setActiveProfiles(next);
    onVoiceprint({ ...voiceprint, activeProfiles: next, enabled: res.enabled });
  }

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm('删除该声纹档案？')) return;
    await api.deleteProfile(id);
    onVoiceprint({ ...voiceprint, profiles: voiceprint.profiles.filter(p => p.id !== id) });
  }

  async function handleCreateNew() {
    const name = newName.trim() || '新声纹';
    const res = await api.createProfile(name);
    if (res.success && res.profile) {
      const np: VoiceprintProfile = { id: res.profile.id, name, enrollment_complete: false, enrollment_steps: 0 };
      onVoiceprint({ ...voiceprint, profiles: [...voiceprint.profiles, np] });
      setEnrollTarget({ id: res.profile.id, step: 0 });
      setCreatingNew(false);
      setNewName('');
    } else {
      onToast(res.detail ? `创建失败：${res.detail}` : '创建失败');
    }
  }

  function handleEnrollClose() {
    setEnrollTarget(null);
    api.getVoiceprint().then(vp => onVoiceprint(vp));
  }

  return (
    <div>
      <div className="vp-header">
        <span className="vp-subtitle">启用后，仅转录匹配的说话人</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: 'var(--ink3)' }}>
            {voiceprint.enabled ? '已启用' : '已关闭'}
          </span>
          <Toggle checked={voiceprint.enabled} onChange={handleToggle} />
        </div>
      </div>

      <div className="vp-profiles-grid">
        {voiceprint.profiles.map((profile, i) => (
          <div
            key={profile.id}
            className={`vp-card${voiceprint.activeProfiles.includes(profile.id) ? ' active' : ''}`}
            onClick={() => handleProfileClick(profile)}
          >
            {voiceprint.activeProfiles.includes(profile.id) && (
              <div className="vp-card-check">✓</div>
            )}
            <button
              className="btn btn-icon"
              style={{ position: 'absolute', top: 4, left: 4, padding: '1px 5px', fontSize: 11, color: 'var(--ink4)', border: 'none' }}
              onClick={e => handleDelete(e, profile.id)}
              title="删除"
            >
              ✕
            </button>
            <div className="vp-card-icon" style={{ background: VP_COLORS[i % VP_COLORS.length] }}>
              {profile.name[0]?.toUpperCase() ?? '?'}
            </div>
            <div className="vp-card-name">{profile.name}</div>
            <div className={`vp-card-status${profile.enrollment_complete ? ' done' : ''}`}>
              {profile.enrollment_complete ? '已完成' : `录制中 ${profile.enrollment_steps}/5`}
            </div>
            {!profile.enrollment_complete && (
              <button
                className="btn btn-ghost btn-sm"
                style={{ marginTop: 8, width: '100%', fontSize: 12 }}
                onClick={e => { e.stopPropagation(); setEnrollTarget({ id: profile.id, step: profile.enrollment_steps }); }}
              >
                继续录制
              </button>
            )}
          </div>
        ))}

        {creatingNew ? (
          <div className="vp-card new-card">
            <input
              type="text"
              placeholder="声纹名称"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreateNew()}
              autoFocus
              style={{ width: '100%', textAlign: 'center' }}
            />
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <button className="btn btn-primary btn-sm" onClick={handleCreateNew}>确认</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setCreatingNew(false)}>取消</button>
            </div>
          </div>
        ) : (
          <div className="vp-card new-card" onClick={() => setCreatingNew(true)}>
            <span style={{ fontSize: 22, color: 'var(--ink3)' }}>+</span>
            <span>新建声纹</span>
          </div>
        )}
      </div>

      {enrollTarget && (
        <EnrollModal
          profileId={enrollTarget.id}
          initialStep={enrollTarget.step}
          sentences={voiceprint.sentences}
          onClose={handleEnrollClose}
          onToast={onToast}
        />
      )}
    </div>
  );
}

// ─── Main Settings Page ───────────────────────────────────────────────────────
const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'mic', label: '麦克风' },
  { id: 'wakeup', label: '唤醒方式' },
  { id: 'asr', label: '服务配置' },
  { id: 'ai', label: '处理模式' },
  { id: 'voiceprint', label: '声纹识别' },
];

export function SettingsPage(props: Props) {
  const [tab, setTab] = useState<SettingsTab>('mic');

  return (
    <div className="settings-page">
      <div className="page-header" style={{ paddingBottom: 0 }}>
        <span className="page-title">设置</span>
      </div>

      <div className="settings-tabs">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`settings-tab${tab === t.id ? ' active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="settings-body">
        {tab === 'mic'        && <MicTab       {...props} />}
        {tab === 'wakeup'     && <WakeupTab    {...props} />}
        {tab === 'asr'        && <AsrTab       {...props} />}
        {tab === 'ai'         && <AiTab        {...props} />}
        {tab === 'voiceprint' && <VoiceprintTab {...props} />}
      </div>
    </div>
  );
}
