export interface Mode {
  id: string;
  name: string;
  description: string;
  isCustom?: boolean;
  prompt?: string;
}

export interface Device {
  id: string;
  name: string;
  is_default: boolean;
  endpoint_id?: string;
}

export interface AsrConfig {
  backend: 'volcengine' | 'local';
}

export interface CloudAsrConfig {
  volcengine?: {
    api_key: string;
    model_id: string;
  };
}

export interface LlmConfig {
  apiBaseUrl: string;
  apiKey: string;
  model: string;
  timeoutSeconds: number;
  temperature: number;
}

export interface AudioConfig {
  device?: string;
  preferred_device?: string;
}

export interface Settings {
  asr?: AsrConfig;
  cloud_asr?: CloudAsrConfig;
  llm?: LlmConfig;
  translateTargetLanguage?: string;
  prompts?: Record<string, string>;
  currentMode?: string;
  audio?: AudioConfig;
}

export interface LocalAsrStatus {
  downloaded: boolean;
  models: { name: string; downloaded: boolean }[];
  downloading: boolean;
  overall_progress: number;
  error: string | null;
}

export interface WakeupConfig {
  methods: string[];
  hotkey_combo: string;
  start_keywords: string[];
  end_keywords: string[];
  undo_hotkey?: string;
  command_keywords?: Record<string, string>;
}

export interface VoiceprintProfile {
  id: string;
  name: string;
  enrollment_complete: boolean;
  enrollment_steps: number;
}

export interface VoiceprintData {
  profiles: VoiceprintProfile[];
  activeProfiles: string[];
  sentences: string[];
  enabled: boolean;
}

export interface RecordingState {
  status: string;
  text: string | null;
}

export interface HistoryItem {
  id: string;
  timestamp: number;
  text: string;
  originalText?: string;
  mode: string;
}

export type Page = 'home' | 'history' | 'settings';

export type SettingsTab = 'mic' | 'wakeup' | 'asr' | 'ai' | 'voiceprint';

export interface ServiceStatus {
  mic: 'ok' | 'error' | 'unconfigured';
  asr: 'ok' | 'error' | 'unconfigured';
  ai: 'ok' | 'error' | 'unconfigured';
}
