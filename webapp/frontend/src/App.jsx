import React, { useState, useRef, useEffect } from 'react'
import ChatWindow from './components/ChatWindow'
import InputBar from './components/InputBar'
import Header from './components/Header'

export default function App() {
  const [messages, setMessages] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef(null)

  const sendMessage = async (text) => {
    if (!text.trim() || isStreaming) return

    const userMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMessage])

    const assistantMessage = { role: 'assistant', content: '', sources: [] }
    setMessages(prev => [...prev, assistantMessage])
    setIsStreaming(true)

    const history = messages.map(m => ({ role: m.role, content: m.content }))

    try {
      abortRef.current = new AbortController()

      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
        signal: abortRef.current.signal,
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6)
          if (!raw) continue

          try {
            const data = JSON.parse(raw)

            if (data.type === 'sources') {
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  sources: data.sources,
                }
                return updated
              })
            } else if (data.type === 'token') {
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: updated[updated.length - 1].content + data.content,
                }
                return updated
              })
            }
          } catch (e) {
            // skip malformed JSON
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: "Erreur de connexion au serveur. Veuillez reessayer.",
            error: true,
          }
          return updated
        })
      }
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }

  const stopStreaming = () => {
    if (abortRef.current) {
      abortRef.current.abort()
    }
  }

  const clearChat = () => {
    if (!isStreaming) {
      setMessages([])
    }
  }

  return (
    <div className="app">
      <Header onClear={clearChat} messagesCount={messages.length} />
      <ChatWindow messages={messages} isStreaming={isStreaming} />
      <InputBar
        onSend={sendMessage}
        onStop={stopStreaming}
        isStreaming={isStreaming}
      />
    </div>
  )
}
