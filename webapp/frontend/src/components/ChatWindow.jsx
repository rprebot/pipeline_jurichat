import React, { useRef, useEffect } from 'react'
import MessageBubble from './MessageBubble'
import { Scale } from 'lucide-react'

export default function ChatWindow({ messages, isStreaming }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="chat-window">
        <div className="welcome">
          <div className="welcome-icon">
            <Scale size={48} />
          </div>
          <h2>Bienvenue sur JuriChat</h2>
          <p>
            Posez vos questions en droit social. Je consulte ma base de
            jurisprudences et d'articles juridiques pour vous fournir des
            reponses sourcees.
          </p>
          <div className="welcome-examples">
            <p className="examples-title">Exemples de questions :</p>
            <div className="examples-grid">
              <div className="example-card">
                Quelles sont les conditions de validite d'un licenciement pour faute grave ?
              </div>
              <div className="example-card">
                Quelle est la duree du preavis en cas de demission d'un CDI ?
              </div>
              <div className="example-card">
                Un employeur peut-il modifier unilateralement la remuneration d'un salarie ?
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-window">
      <div className="messages">
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            isLast={i === messages.length - 1}
            isStreaming={isStreaming && i === messages.length - 1}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
