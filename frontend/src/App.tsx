import { useState, useEffect, useCallback, useRef } from 'react';
import './app.css';
import { api } from './api';
import type { Mode, Device, Settings, WakeupConfig, VoiceprintData, RecordingState, HistoryItem, Page } from './types';
import { Sidebar } from './components/Sidebar';
import { HomePage } from './components/HomePage';
import { HistoryPage } from './components/HistoryPage';
import { SettingsPage } from './components/SettingsPage';
import { Toast } from './components/Toast';

const HISTORY_KEY = 'shokztype_history';
const HISTORY_MAX = 100;

function loadHistory(): HistoryItem[] {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]'); } catch { return []; }
}
function saveHistory(items: HistoryItem[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, HISTORY_MAX)));
}

export default function App() {
  const [page, setPage] = useState<Page>('home');
  const [modes, setModes] = useState<Mode[]>([]);
  const [currentMode, setCurrentMode] = useState('translate');
  const [settings, setSettings] = useState<Settings>({});
  const [devices, setDevices] = useState<Device[]>([]);
  const [wakeup, setWakeup] = useState<WakeupConfig>({ methods: ['hotkey'], hotkey_combo: 'F9', start_keywords: [], end_keywords: [], undo_hotkey: 'ctrl+shift+z', command_keywords: { '帮我撤销': 'undo' } });
  const [voiceprint, setVoiceprint] = useState<VoiceprintData>({ profiles: [], activeProfiles: [], sentences: [], enabled: false });
  const [recordingState, setRecordingState] = useState<RecordingState>({ status: 'loading', text: null });
  const [toast, setToast] = useState('');
  const [history, setHistory] = useState<HistoryItem[]>(loadHistory);

  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentModeRef = useRef(currentMode);
  const modesRef = useRef<Mode[]>([]);
  const prevStateRef = useRef<RecordingState>({ status: '', text: null });
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => { currentModeRef.current = currentMode; }, [currentMode]);
  useEffect(() => { modesRef.current = modes; }, [modes]);

  function playTone(freq: number, durationMs: number, volume = 0.25) {
    try {
      if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
      const ctx = audioCtxRef.current;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(volume, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + durationMs / 1000);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + durationMs / 1000);
    } catch { /* 静默失败 */ }
  }

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(''), 2500);
  }, []);

  // --- Recording SSE ---
  useEffect(() => {
    const es = new EventSource('/api/recording/stream');
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.event === 'mode_changed') {
          setCurrentMode(data.mode);
          const name = modesRef.current.find(m => m.id === data.mode)?.name ?? data.mode;
          showToast('已切换到 ' + name);
        } else if (data.event === 'result' && data.text?.trim()) {
          // Explicit result event (mock preview + real backend)
          setHistory(prev => {
            const item: HistoryItem = {
              id: Date.now().toString(),
              timestamp: Date.now(),
              text: data.text,
              originalText: data.original_text ?? undefined,
              mode: currentModeRef.current,
            };
            const next = [item, ...prev].slice(0, HISTORY_MAX);
            saveHistory(next);
            return next;
          });
        } else if (data.event === 'state') {
          const state: RecordingState = { status: data.status, text: data.text ?? null };
          setRecordingState(state);

          // 声音反馈
          const prev = prevStateRef.current;
          if (data.status === 'recording' || data.status === 'active') {
            playTone(880, 150);
          } else if (
            (prev.status === 'active' || prev.status === 'recording' || prev.status === 'processing') &&
            (data.status === 'idle' || data.status === 'ready')
          ) {
            playTone(600, 120);
          } else if (data.status === 'error') {
            playTone(400, 250);
          }

          prevStateRef.current = state;
        }
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, []);

  // --- Device SSE ---
  useEffect(() => {
    const es = new EventSource('/api/devices/stream');
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.event === 'device_switched') {
          setDevices(data.devices);
          setSettings(prev => ({ ...prev, audio: { ...prev.audio, device: data.new_device.id } }));
          showToast(data.reason === 'preferred_reconnected'
            ? '偏好麦克风已重新连接: ' + data.new_device.name
            : '麦克风已切换到: ' + data.new_device.name
          );
        } else if (data.event === 'devices_changed') {
          setDevices(data.devices);
        }
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, [showToast]);

  // --- Initial load ---
  useEffect(() => {
    (async () => {
      const [modesData, settingsData, devicesData, wakeupData] = await Promise.all([
        api.getModes(),
        api.getSettings(),
        api.getDevices(),
        api.getWakeup(),
      ]);
      setModes(modesData.modes);
      setCurrentMode(modesData.currentMode);
      setSettings(settingsData);
      setDevices(devicesData.devices);
      // Normalize wakeup: backend may return {methods:[...]} or old {method:...}
      const w = wakeupData as unknown as Record<string, unknown>;
      const methods: string[] = Array.isArray(w.methods) ? w.methods as string[]
        : [(w.method as string) ?? 'hotkey'];
      setWakeup({ ...wakeupData, methods });
    })();
  }, []);

  async function handleSetMode(mode: string) {
    await api.setMode(mode);
    setCurrentMode(mode);
    showToast('已切换到 ' + (modes.find(m => m.id === mode)?.name ?? mode));
  }

  async function handleCreateCustomMode(name: string, prompt: string) {
    const res = await api.createCustomMode(name, prompt);
    if (res.success && res.id) {
      const [data, wakeupData] = await Promise.all([api.getModes(), api.getWakeup()]);
      setModes(data.modes);
      await api.setMode(res.id);
      setCurrentMode(res.id);
      const w = wakeupData as unknown as Record<string, unknown>;
      const methods: string[] = Array.isArray(w.methods) ? w.methods as string[] : [(w.method as string) ?? 'hotkey'];
      setWakeup({ ...wakeupData, methods });
    }
    return res;
  }

  async function handleUpdateModePrompt(id: string, prompt: string) {
    await api.saveSettings({ prompts: { [id]: prompt } });
    const [modesData, settingsData] = await Promise.all([api.getModes(), api.getSettings()]);
    setModes(modesData.modes);
    setSettings(settingsData);
  }

  async function handleUpdateCustomMode(id: string, data: { name?: string; prompt?: string }) {
    await api.updateCustomMode(id, data);
    const [modesData, settingsData] = await Promise.all([api.getModes(), api.getSettings()]);
    setModes(modesData.modes);
    setSettings(settingsData);
  }

  async function handleUpdateModeDescription(id: string, description: string) {
    await api.updateModeDescription(id, description);
    const modesData = await api.getModes();
    setModes(modesData.modes);
  }

  async function handleDeleteCustomMode(id: string) {
    await api.deleteCustomMode(id);
    const [modesData, settingsData] = await Promise.all([api.getModes(), api.getSettings()]);
    setModes(modesData.modes);
    setCurrentMode(modesData.currentMode);
    setSettings(settingsData);
  }

  function handleNavigate(p: Page) {
    setPage(p);
    if (p === 'settings') {
      // Refresh voiceprint when entering settings
      api.getVoiceprint().then(vp => setVoiceprint(vp));
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        page={page}
        onNavigate={handleNavigate}
        settings={settings}
        wakeup={wakeup}
      />

      <main className="page-content">
        {page === 'home' && (
          <HomePage
            modes={modes}
            currentMode={currentMode}
            recordingState={recordingState}
            wakeup={wakeup}
            history={history}
            asrBackend={settings.asr?.backend}
            onSetMode={handleSetMode}
            onUpdateModePrompt={handleUpdateModePrompt}
            onCreateCustomMode={handleCreateCustomMode}
            onUpdateCustomMode={handleUpdateCustomMode}
            onDeleteCustomMode={handleDeleteCustomMode}
            onToast={showToast}
          />
        )}
        {page === 'history' && (
          <HistoryPage
            history={history}
            modes={modes}
            onClear={() => { setHistory([]); saveHistory([]); }}
            onDelete={(id) => { const next = history.filter(h => h.id !== id); setHistory(next); saveHistory(next); }}
            onToast={showToast}
          />
        )}
        {page === 'settings' && (
          <SettingsPage
            settings={settings}
            devices={devices}
            wakeup={wakeup}
            voiceprint={voiceprint}
            modes={modes}
            onSettings={async (s) => { setSettings(s); const m = await api.getModes(); setModes(m.modes); }}
            onWakeup={setWakeup}
            onVoiceprint={setVoiceprint}
            onCreateCustomMode={handleCreateCustomMode}
            onUpdateModePrompt={handleUpdateModePrompt}
            onUpdateModeDescription={handleUpdateModeDescription}
            onDeleteCustomMode={handleDeleteCustomMode}
            onToast={showToast}
          />
        )}
      </main>

      <Toast message={toast} />
    </div>
  );
}
