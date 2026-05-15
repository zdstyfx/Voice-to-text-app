import { useState, useRef, useEffect } from 'react';
import type { Mode, RecordingState, WakeupConfig, HistoryItem } from '../types';

interface Props {
  modes: Mode[];
  currentMode: string;
  recordingState: RecordingState;
  wakeup: WakeupConfig;
  history: HistoryItem[];
  asrBackend?: string;
  onSetMode: (id: string) => void;
  onUpdateModePrompt: (id: string, prompt: string) => Promise<void>;
  onCreateCustomMode: (name: string, prompt: string) => Promise<{ success: boolean; error?: string }>;
  onUpdateCustomMode: (id: string, data: { name?: string; prompt?: string }) => Promise<void>;
  onDeleteCustomMode: (id: string) => Promise<void>;
  onToast: (msg: string) => void;
}

function formatHotkey(combo: string) {
  return combo.toUpperCase().replace(/\+/g, ' + ');
}

function getWakeupDescription(wakeup: WakeupConfig): { main: string; sub: string } {
  const methods = wakeup.methods ?? [];
  const hasHotkey = methods.includes('hotkey');
  const hasVad = methods.includes('vad');

  if (hasHotkey && hasVad) {
    return {
      main: `按下 ${formatHotkey(wakeup.hotkey_combo)} 开始`,
      sub: `当前唤醒方式: 热键 ${formatHotkey(wakeup.hotkey_combo)} 或语音唤醒`,
    };
  }
  if (hasVad) {
    const kw = wakeup.start_keywords?.[0];
    return {
      main: kw ? `说出"${kw}"开始` : '等待语音唤醒',
      sub: '当前唤醒方式: 语音唤醒',
    };
  }
  return {
    main: `按下 ${formatHotkey(wakeup.hotkey_combo)} 开始`,
    sub: `当前唤醒方式: 热键 ${formatHotkey(wakeup.hotkey_combo)}`,
  };
}

function getRecordingHint(wakeup: WakeupConfig, status: string): string {
  if (status === 'processing') return '处理中...';
  const methods = wakeup.methods ?? [];
  const hasHotkey = methods.includes('hotkey');
  if (hasHotkey) return `再按 ${formatHotkey(wakeup.hotkey_combo)} 结束`;
  return '说出结束词停止';
}

type EditState =
  | { type: 'none' }
  | { type: 'create'; name: string; prompt: string }
  | { type: 'edit'; id: string; name: string; prompt: string; isCustom: boolean };

export function HomePage({ modes, currentMode, recordingState, wakeup, history, asrBackend, onSetMode, onUpdateModePrompt, onCreateCustomMode, onUpdateCustomMode, onDeleteCustomMode, onToast }: Props) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [editState, setEditState] = useState<EditState>({ type: 'none' });
  const [saving, setSaving] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const isRecording = recordingState.status === 'recording' || recordingState.status === 'active';
  const isProcessing = recordingState.status === 'processing';

  const currentModeObj = modes.find(m => m.id === currentMode);
  const { main: hintMain, sub: hintSub } = getWakeupDescription(wakeup);
  const lastResult = history[0]?.text ?? '';

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
        setEditState({ type: 'none' });
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  async function handleCopy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      onToast('已复制到剪贴板');
    } catch {
      onToast('复制失败');
    }
  }

  function openCreate() {
    setEditState({
      type: 'create',
      name: '',
      prompt: '# 示例 Prompt（可直接修改）\n你是语音转写纠错专家。修正以下语音识别文字中的错误（同音字误识、断句不自然等），保持原意，只输出修正后的文字：\n\n{text}',
    });
  }

  function openEdit(m: Mode, e: React.MouseEvent) {
    e.stopPropagation();
    setEditState({ type: 'edit', id: m.id, name: m.name, prompt: m.prompt ?? '', isCustom: !!m.isCustom });
  }

  async function handleSave() {
    if (editState.type === 'none') return;
    setSaving(true);
    try {
      if (editState.type === 'create') {
        const res = await onCreateCustomMode(editState.name.trim(), editState.prompt.trim());
        if (res.success) {
          onToast('已创建模式');
          setEditState({ type: 'none' });
          setDropdownOpen(false);
        } else {
          onToast(res.error ?? '创建失败');
        }
      } else if (editState.isCustom) {
        await onUpdateCustomMode(editState.id, { name: editState.name.trim(), prompt: editState.prompt.trim() });
        onToast('已保存');
        setEditState({ type: 'none' });
      } else {
        await onUpdateModePrompt(editState.id, editState.prompt.trim());
        onToast('Prompt 已保存');
        setEditState({ type: 'none' });
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    await onDeleteCustomMode(id);
    onToast('已删除');
    setEditState({ type: 'none' });
  }

  const editTitle = editState.type === 'create' ? '新建自定义模式' : '编辑模式';
  const editNameVal = editState.type !== 'none' ? editState.name : '';
  const editPromptVal = editState.type !== 'none' ? editState.prompt : '';
  const editId = editState.type === 'edit' ? editState.id : null;

  return (
    <div className="home-page">
      {/* Page header */}
      <div className="page-header">
        <span className="page-title">语音输入</span>

        <div className="mode-dropdown-wrap" ref={dropdownRef}>
          <button
            className="mode-btn"
            onClick={() => { setDropdownOpen(v => !v); setEditState({ type: 'none' }); }}
          >
            {currentModeObj?.name ?? '转写'}
            <span className={`mode-btn-arrow${dropdownOpen ? ' open' : ''}`}>▾</span>
          </button>

          {dropdownOpen && (
            <div className="mode-dropdown">
              {editState.type === 'none' ? (
                <>
                  {modes.map(m => (
                    <div
                      key={m.id}
                      className={`mode-option${m.id === currentMode ? ' active' : ''}`}
                      onClick={() => { onSetMode(m.id); setDropdownOpen(false); }}
                    >
                      <span className="mode-option-check">
                        {m.id === currentMode && '✓'}
                      </span>
                      <div className="mode-option-info">
                        <div className="mode-option-name">{m.name}</div>
                        <div className="mode-option-desc">{m.description}</div>
                      </div>
                      {m.id !== 'transcribe' && (
                        <button
                          className="mode-option-edit-btn"
                          onClick={e => openEdit(m, e)}
                          title="编辑 Prompt"
                        >
                          ✎
                        </button>
                      )}
                    </div>
                  ))}
                  <div className="mode-option mode-option-add" onClick={openCreate}>
                    <span className="mode-option-check" />
                    <div className="mode-option-info">
                      <div className="mode-option-name" style={{ color: 'var(--accent)' }}>+ 自定义模式</div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="mode-edit-panel" onClick={e => e.stopPropagation()}>
                  <div className="mode-edit-title">{editTitle}</div>
                  {(editState.type === 'create' || (editState.type === 'edit' && editState.isCustom)) && (
                    <input
                      className="mode-edit-input"
                      placeholder="模式名称"
                      value={editNameVal}
                      onChange={e => setEditState(s => s.type !== 'none' ? { ...s, name: e.target.value } : s)}
                      autoFocus
                    />
                  )}
                  <textarea
                    className="mode-edit-prompt"
                    placeholder={"Prompt 模板，用 {text} 代表转写文本\n\n示例：\n你是语音转写纠错专家。修正以下语音识别文字中的错误，只输出修正后的文字：\n{text}"}
                    rows={6}
                    value={editPromptVal}
                    onChange={e => setEditState(s => s.type !== 'none' ? { ...s, prompt: e.target.value } : s)}
                    spellCheck={false}
                    autoFocus={editState.type === 'edit' && !editState.isCustom}
                  />
                  <div className="mode-edit-actions">
                    {editId && editState.type === 'edit' && editState.isCustom && (
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ color: 'var(--red)', marginRight: 'auto' }}
                        onClick={e => handleDelete(editId, e)}
                      >
                        删除
                      </button>
                    )}
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => setEditState({ type: 'none' })}
                    >
                      取消
                    </button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={handleSave}
                      disabled={saving || !editNameVal.trim()}
                    >
                      {saving ? '保存中...' : '保存'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="home-main">
        <div className="recording-visual">
          {/* Circle with pulse rings */}
          <div className="record-circle-wrap">
            {isRecording && (
              <>
                <div className="record-ring record-ring-1" />
                <div className="record-ring record-ring-2" />
                <div className="record-ring record-ring-3" />
              </>
            )}
            <div className={`record-circle${isRecording ? ' recording' : ''}`} />
          </div>

          {/* Status text */}
          <div className={`record-status-text${isRecording ? ' recording' : isProcessing ? ' processing' : ''}`}>
            {isRecording ? '录音中' : isProcessing ? '处理中' : '待唤醒'}
          </div>

          {/* Hint */}
          {isRecording ? (
            <div className="record-hint">
              <span className="record-hint-dot" />
              {getRecordingHint(wakeup, recordingState.status)}
            </div>
          ) : isProcessing ? (
            <div className="record-hint">正在识别...</div>
          ) : (
            <>
              <div className="record-hint">{hintMain}</div>
              <div className="wakeup-label">{hintSub}</div>
            </>
          )}
        </div>

        {/* Realtime text — shown during recording */}
        {isRecording && (
          <div className="realtime-area">
            <div className="realtime-divider" />
            {recordingState.text
              ? <div className="realtime-confirmed">{recordingState.text}</div>
              : asrBackend === 'local' && (
                  <div className="realtime-local-hint">本地模式下识别结果将在录音结束后显示</div>
                )
            }
          </div>
        )}
      </div>

      {/* Bottom bar */}
      <div className="home-bottom-bar">
        <span className={`bottom-last-text${lastResult ? ' has-result' : ''}`}>
          {lastResult || '录音完成后，结果将显示在这里'}
        </span>
        {lastResult && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => handleCopy(lastResult)}
          >
            复制
          </button>
        )}
      </div>
    </div>
  );
}
