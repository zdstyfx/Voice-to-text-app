interface Props {
  message: string;
}

export function Toast({ message }: Props) {
  return (
    <div className="toast-wrap">
      <div className={`toast${message ? ' show' : ''}`}>
        <span style={{ color: 'var(--green)', fontSize: 15 }}>✓</span>
        {message}
      </div>
    </div>
  );
}
