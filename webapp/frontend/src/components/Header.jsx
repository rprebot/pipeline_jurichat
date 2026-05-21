import React from 'react'
import { Scale, Trash2 } from 'lucide-react'

export default function Header({ onClear, messagesCount }) {
  return (
    <header className="header">
      <div className="header-left">
        <Scale size={28} className="header-icon" />
        <div>
          <h1>JuriChat</h1>
          <span className="header-subtitle">Assistant juridique en droit social</span>
        </div>
      </div>
      {messagesCount > 0 && (
        <button className="btn-clear" onClick={onClear} title="Nouvelle conversation">
          <Trash2 size={18} />
          <span>Effacer</span>
        </button>
      )}
    </header>
  )
}
