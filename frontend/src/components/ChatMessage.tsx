import React from 'react';

export type ChatRole = 'user' | 'assistant';

export interface ChatMessageProps {
  role: ChatRole;
  content: string;
  isStreaming?: boolean;
  onCopy?: (content: string) => void;
}

export const ChatMessageBubble: React.FC<ChatMessageProps> = ({
  role,
  content,
  isStreaming,
  onCopy
}) => {
  const isUser = role === 'user';
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      onCopy?.(content);
    } catch {
      // no-op
    }
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} text-sm leading-relaxed`}>
      <div className="max-w-3xl space-y-1">
        <div
          className={`chat-bubble ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'} relative overflow-hidden group`}
        >
          <div className="whitespace-pre-wrap">{content}</div>
          {isStreaming && (
            <span className="absolute bottom-3 right-4 h-2 w-6 rounded-full bg-slate-300 animate-pulse" />
          )}
          {!isStreaming && (
            <button
              type="button"
              aria-label="Copy message"
              className="chat-bubble-copy opacity-0 group-hover:opacity-100"
              onClick={handleCopy}
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path d="M6 2a2 2 0 0 0-2 2v9h2V4h7V2H6Zm3 4a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2H9Zm0 2h6v8H9V8Z" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
