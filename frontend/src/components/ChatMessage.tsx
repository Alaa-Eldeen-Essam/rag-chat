import React, { useMemo, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export type ChatRole = 'user' | 'assistant';
export type ChatCopyMode = 'plain_text' | 'raw_markdown';

export interface ChatMessageProps {
  role: ChatRole;
  content: string;
  isStreaming?: boolean;
  onCopy?: (content: string) => void;
  renderAsMarkdown?: boolean;
  copyMode?: ChatCopyMode;
}

export const ChatMessageBubble: React.FC<ChatMessageProps> = ({
  role,
  content,
  isStreaming,
  onCopy,
  renderAsMarkdown = false,
  copyMode = 'raw_markdown'
}) => {
  const isUser = role === 'user';
  const contentRef = useRef<HTMLDivElement | null>(null);
  const shouldRenderMarkdown = !isUser && renderAsMarkdown;

  const renderedText = useMemo(() => {
    if (copyMode === 'raw_markdown') return content;
    const text = contentRef.current?.innerText;
    if (typeof text === 'string' && text.trim().length > 0) return text;
    return content;
  }, [copyMode, content]);

  const isSafeLink = (href: string): boolean => {
    const value = href.trim().toLowerCase();
    return (
      value.startsWith('http://') ||
      value.startsWith('https://') ||
      value.startsWith('mailto:')
    );
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(renderedText);
      onCopy?.(renderedText);
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
          <div ref={contentRef}>
            {shouldRenderMarkdown ? (
              <div className="markdown-body">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  skipHtml
                  components={{
                    a: ({ href, children, ...props }) => {
                      const safeHref = typeof href === 'string' && isSafeLink(href) ? href : '#';
                      return (
                        <a
                          {...props}
                          href={safeHref}
                          target="_blank"
                          rel="noopener noreferrer nofollow"
                        >
                          {children}
                        </a>
                      );
                    },
                    pre: ({ children, ...props }) => (
                      <pre {...props} className="markdown-pre">
                        {children}
                      </pre>
                    ),
                    code: ({ children, className, ...props }) => {
                      const text = String(children ?? '');
                      const isBlock = Boolean(className) || text.includes('\n');
                      return (
                        <code
                          {...props}
                          className={isBlock ? 'markdown-code-block' : 'markdown-code-inline'}
                        >
                          {children}
                        </code>
                      );
                    },
                    table: ({ children, ...props }) => (
                      <div className="markdown-table-wrap">
                        <table {...props}>{children}</table>
                      </div>
                    )
                  }}
                >
                  {content}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="whitespace-pre-wrap">{content}</div>
            )}
          </div>
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
