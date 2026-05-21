import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { User, Bot, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react'

function Sources({ sources }) {
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  return (
    <div className="sources">
      <button className="sources-toggle" onClick={() => setExpanded(!expanded)}>
        <span>{sources.length} source{sources.length > 1 ? 's' : ''} consultee{sources.length > 1 ? 's' : ''}</span>
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {expanded && (
        <div className="sources-list">
          {sources.map((s, i) => (
            <a
              key={i}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="source-item"
            >
              <div className="source-info">
                <span className="source-title">{s.title}</span>
                <span className="source-meta">
                  {s.collection} | score: {s.score}
                  {s.date && ` | ${s.date}`}
                </span>
              </div>
              <ExternalLink size={14} />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

export default function MessageBubble({ message, isLast, isStreaming }) {
  const isUser = message.role === 'user'

  return (
    <div className={`message ${isUser ? 'message-user' : 'message-assistant'}`}>
      <div className="message-avatar">
        {isUser ? <User size={20} /> : <Bot size={20} />}
      </div>
      <div className="message-body">
        <div className={`message-content ${message.error ? 'message-error' : ''}`}>
          {isUser ? (
            <p>{message.content}</p>
          ) : (
            <>
              {message.content ? (
                <ReactMarkdown>{message.content}</ReactMarkdown>
              ) : isStreaming ? (
                <div className="typing-indicator">
                  <span></span><span></span><span></span>
                </div>
              ) : null}
              {isStreaming && message.content && <span className="cursor-blink">|</span>}
            </>
          )}
        </div>
        {!isUser && <Sources sources={message.sources} />}
      </div>
    </div>
  )
}
