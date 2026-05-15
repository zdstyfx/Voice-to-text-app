import { useState } from 'react';
import { api } from '../api';

interface Props {
  profileId: string;
  initialStep: number;
  sentences: string[];
  onClose: () => void;
  onToast: (msg: string) => void;
}

const TOTAL = 5;
const STEP_LABELS = ['准备', '第1句', '第2句', '第3句', '第4句', '第5句'];

export function EnrollModal({ profileId, initialStep, sentences, onClose, onToast }: Props) {
  const [step, setStep] = useState(initialStep);
  const [enrolling, setEnrolling] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  const done = step >= TOTAL;

  async function doStep() {
    if (enrolling) {
      await api.stopEnroll();
      setEnrolling(false);
      setStatusMsg('已停止录制');
      return;
    }
    setEnrolling(true);
    setStatusMsg('录制中...');
    try {
      const nextStep = step + 1;
      const resp = await api.enrollStep(profileId, nextStep);
      if (resp.success) {
        setStep(nextStep);
        setStatusMsg(nextStep < TOTAL ? `第 ${nextStep} 步完成` : '全部录制完成！');
      } else {
        setStatusMsg(resp.message || '录制失败，请重试');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setStatusMsg('错误: ' + msg);
      onToast('录音失败: ' + msg);
    } finally {
      setEnrolling(false);
    }
  }

  const currentSentence = sentences[step] ?? '加载中...';

  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">新建声纹</span>
          <button className="btn btn-icon" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {/* Steps */}
          <div className="enroll-steps-outer">
            <div className="enroll-steps-track">
              {Array.from({ length: TOTAL }, (_, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
                  <div className={`enroll-step-circle${i < step ? ' done' : i === step ? ' active' : ''}`}>
                    {i < step ? '✓' : i + 1}
                  </div>
                  {i < TOTAL - 1 && (
                    <div className={`enroll-step-line${i < step ? ' done' : ''}`} />
                  )}
                </div>
              ))}
            </div>
            <div className="enroll-steps-labels">
              {Array.from({ length: TOTAL }, (_, i) => (
                <span
                  key={i}
                  className={`enroll-step-label${i < step ? ' done' : i === step ? ' active' : ''}`}
                >
                  {STEP_LABELS[i + 1]}
                </span>
              ))}
            </div>
          </div>

          {done ? (
            <div style={{ textAlign: 'center', padding: '20px 0' }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>🎉</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--green)' }}>声纹录制完成！</div>
              <div style={{ fontSize: 13, color: 'var(--ink3)', marginTop: 6 }}>您的声纹已成功创建</div>
            </div>
          ) : (
            <>
              <div className="enroll-subtitle">
                第 {step + 1} 步：请朗读下面的句子
              </div>
              <div className="enroll-quote">{currentSentence}</div>
              {enrolling && (
                <div className="enroll-recording-state">
                  <span style={{ fontSize: 12, lineHeight: 1 }}>●</span>
                  录制中... 请朗读上方文本
                </div>
              )}
              {statusMsg && !enrolling && (
                <div style={{ textAlign: 'center', fontSize: 13, color: 'var(--ink3)', marginTop: 8 }}>
                  {statusMsg}
                </div>
              )}
              <div className="enroll-hint">请在安静环境中朗读，时长约 8 秒</div>
            </>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>
            {done ? '关闭' : '取消'}
          </button>
          {!done && (
            <div style={{ display: 'flex', gap: 8 }}>
              {enrolling && (
                <button className="btn btn-secondary" onClick={doStep}>
                  停止
                </button>
              )}
              <button className="btn btn-primary" onClick={doStep} disabled={enrolling && false}>
                {enrolling ? '录制中...' : '开始录制'}
              </button>
            </div>
          )}
          {done && (
            <button className="btn btn-primary" onClick={onClose}>
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
