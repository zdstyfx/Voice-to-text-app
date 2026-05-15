import type { Mode, Device, Settings, WakeupConfig, VoiceprintData, LocalAsrStatus } from './types';

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  getModes: () => request<{ modes: Mode[]; currentMode: string }>('/api/modes'),
  setMode: (mode: string) => request('/api/modes/current', 'POST', { mode }),
  createCustomMode: (name: string, prompt: string) => request<{ success: boolean; id?: string; name?: string; error?: string }>('/api/modes/custom', 'POST', { name, prompt }),
  updateCustomMode: (id: string, data: { name?: string; prompt?: string }) => request<{ success: boolean }>(`/api/modes/custom/${encodeURIComponent(id)}`, 'PUT', data),
  updateModeDescription: (id: string, description: string) => request<{ success: boolean }>(`/api/modes/${encodeURIComponent(id)}/description`, 'PATCH', { description }),
  deleteCustomMode: (id: string) => request<{ success: boolean }>(`/api/modes/custom/${encodeURIComponent(id)}`, 'DELETE'),

  getSettings: () => request<Settings>('/api/settings'),
  saveSettings: (body: Partial<Settings>) => request('/api/settings', 'POST', body),

  getDevices: () => request<{ devices: Device[] }>('/api/devices'),

  getWakeup: () => request<WakeupConfig>('/api/wakeup'),
  saveWakeup: (body: Partial<WakeupConfig>) => request<{ success: boolean; error?: string }>('/api/wakeup', 'POST', body),
  recordHotkey: () => request<{ success: boolean; combo: string }>('/api/wakeup/record-hotkey', 'POST'),
  addStartKeyword: (keyword: string) => request<{ success: boolean; error?: string }>('/api/wakeup/add-start-keyword', 'POST', { keyword }),
  deleteStartKeyword: (name: string) => request(`/api/wakeup/start-keywords/${encodeURIComponent(name)}`, 'DELETE'),
  addEndKeyword: (keyword: string) => request<{ success: boolean; error?: string }>('/api/wakeup/add-end-keyword', 'POST', { keyword }),
  deleteEndKeyword: (name: string) => request(`/api/wakeup/end-keywords/${encodeURIComponent(name)}`, 'DELETE'),

  getVoiceprint: () => request<VoiceprintData>('/api/voiceprint/profiles'),
  createProfile: (name: string) => request<{ success: boolean; profile?: { id: string }; detail?: string }>('/api/voiceprint/profiles', 'POST', { name }),
  deleteProfile: (id: string) => request<{ voiceprint_disabled?: boolean }>(`/api/voiceprint/profiles/${id}`, 'DELETE'),
  setActiveProfiles: (profile_ids: string[]) => request<{ enabled: boolean }>('/api/voiceprint/active', 'PUT', { profile_ids }),
  toggleVoiceprint: () => request<{ success: boolean; enabled?: boolean; error?: string }>('/api/voiceprint/toggle', 'POST'),
  enrollStep: (profileId: string, step: number) =>
    request<{ success: boolean; message?: string }>(`/api/voiceprint/profiles/${profileId}/enroll?step=${step}&duration=5`, 'POST', {}),
  stopEnroll: () => request('/api/voiceprint/enroll/stop', 'POST'),

  getHealth: () => request<{ status: string }>('/api/health'),

  undoLastOutput: () => request<{ success: boolean; chars?: number; message?: string }>('/api/recording/undo', 'POST'),
  addCommandKeyword: (keyword: string, action = 'undo') => request<{ success: boolean; error?: string }>('/api/wakeup/add-command-keyword', 'POST', { keyword, action }),
  deleteCommandKeyword: (name: string) => request(`/api/wakeup/command-keywords/${encodeURIComponent(name)}`, 'DELETE'),
  saveUndoHotkey: (combo: string) => request<{ success: boolean; error?: string }>('/api/wakeup/undo-hotkey', 'POST', { combo }),

  getLocalAsrStatus: () => request<LocalAsrStatus>('/api/asr/local/status'),
  startLocalAsrDownload: () => request<{ success: boolean; message?: string }>('/api/asr/local/download', 'POST'),
};
