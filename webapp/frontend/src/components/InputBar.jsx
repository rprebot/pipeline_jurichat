import React, { useState, useRef, useEffect } from 'react'
import { Send, Square } from 'lucide-react'

export default function InputBar({ onSend, onStop, isStreaming }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!isStreaming && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [isStreaming])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (text.trim() && !isStreaming) {
      onSend(text)
      setText('')
      // Reset textarea height
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto'
      }
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const handleInput = (e) => {
    setText(e.target.value)
    // Auto-resize
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  return (
    <div className="input-bar-container">
      <form className="input-bar" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Posez votre question en droit social..."
          rows={1}
          disabled={isStreaming}
        />
        {isStreaming ? (
          <button type="button" className="btn-stop" onClick={onStop} title="Arreter">
            <Square size={18} />
          </button>
        ) : (
          <button
            type="submit"
            className="btn-send"
            disabled={!text.trim()}
            title="Envoyer"
          >
            <Send size={18} />
          </button>
        )}
      </form>
      <p className="input-disclaimer">
        JuriChat peut faire des erreurs. Verifiez les informations importantes.
      </p>
    </div>
  )
}
