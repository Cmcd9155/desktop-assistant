import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from 'react'
import './App.css'

type CompanionState = 'idle' | 'thinking' | 'smiling' | 'frowning' | 'moderated'
type ImageStatus = 'queued' | 'running' | 'completed' | 'moderated' | 'failed'

type Message = {
  role: 'user' | 'assistant'
  text: string
}

type CompanionSettings = {
  bio: string
  instructions: string
  baseImagePath: string
  nsfwEnabled: boolean
  memoryEnabled: boolean
}

type MemoryItem = {
  id: string
  text: string
  category: string
  storedAt: string
}

type ChatTurnResponse = {
  replyText: string
  imageJobId: string
  emotion: CompanionState
  openclawRequestId?: string | null
  warnings: string[]
}

type ChatTurnRequest = {
  message: string
  includeOpenClaw: boolean
  imageWidth?: number
  imageHeight?: number
}

type ChatImageResponse = {
  status: ImageStatus
  imageUrl?: string | null
  moderated?: boolean
  errorCode?: string | null
}

type OpenClawEvent = {
  requestId: string
  sourceSession: string
  role: string
  text: string
  ts: string
}

type OpenClawPollResponse = {
  events: OpenClawEvent[]
  cursor: string
}

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8787'

const defaultSettings: CompanionSettings = {
  bio: 'Helpful desktop companion.',
  instructions: 'Be concise, clear, and useful.',
  baseImagePath: '',
  nsfwEnabled: true,
  memoryEnabled: true,
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const bodyIsFormData = init.body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(bodyIsFormData ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  })
  if (!response.ok) {
    throw new Error(await response.text())
  }
  return (await response.json()) as T
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function resolveAssetPath(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_BASE}${url}`
}

function resolveBaseImagePreview(path: string | null | undefined): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/static/')) {
    return resolveAssetPath(path)
  }

  const normalized = path.replace(/\\/g, '/')
  const uploadsIndex = normalized.lastIndexOf('/uploads/')
  if (uploadsIndex >= 0) {
    const relativeUploadsPath = normalized.slice(uploadsIndex)
    return resolveAssetPath(`/static${relativeUploadsPath}`)
  }

  const parts = normalized.split('/')
  const fileName = parts[parts.length - 1]
  if (!fileName) return ''
  return resolveAssetPath(`/static/uploads/${encodeURIComponent(fileName)}`)
}

function App() {
  const [tab, setTab] = useState<'chat' | 'settings'>('chat')
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', text: 'Ready. Ask me anything to begin the turn loop.' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [includeOpenClaw, setIncludeOpenClaw] = useState(false)
  const [companionState, setCompanionState] = useState<CompanionState>('idle')
  const [imageUrl, setImageUrl] = useState('')
  const [toast, setToast] = useState('')
  const [settings, setSettings] = useState<CompanionSettings>(defaultSettings)
  const [memoryQuery, setMemoryQuery] = useState('')
  const [memoryItems, setMemoryItems] = useState<MemoryItem[]>([])
  const [openClawCursor, setOpenClawCursor] = useState('')
  const [openClawEvents, setOpenClawEvents] = useState<OpenClawEvent[]>([])
  const chatPanelRef = useRef<HTMLElement | null>(null)
  const activeTabLabel = tab === 'chat' ? 'Chat Console' : 'Companion Settings'

  const stateLabel = useMemo(() => companionState.toUpperCase(), [companionState])

  useEffect(() => {
    void loadSettings()
    void loadMemory()
  }, [])

  useEffect(() => {
    if (!toast) return
    const timeout = setTimeout(() => setToast(''), 3500)
    return () => clearTimeout(timeout)
  }, [toast])

  async function loadSettings(): Promise<void> {
    const current = await api<CompanionSettings>('/api/settings/companion')
    setSettings(current)
    setImageUrl(resolveBaseImagePreview(current.baseImagePath))
  }

  async function loadMemory(query = ''): Promise<void> {
    const encoded = encodeURIComponent(query)
    const data = await api<{ items: MemoryItem[] }>(`/api/memory?query=${encoded}`)
    setMemoryItems(data.items)
  }

  async function pollImage(jobId: string, emotion: CompanionState): Promise<void> {
    const deadline = Date.now() + 45_000
    while (Date.now() < deadline) {
      const status = await api<ChatImageResponse>(`/api/chat/image/${jobId}`)
      if (status.status === 'completed') {
        setCompanionState(emotion)
        setImageUrl(resolveAssetPath(status.imageUrl))
        return
      }
      if (status.status === 'moderated') {
        setCompanionState('moderated')
        setImageUrl(resolveAssetPath(status.imageUrl))
        setToast('Image moderated. Previous valid image was kept.')
        return
      }
      if (status.status === 'failed') {
        setCompanionState(emotion)
        setImageUrl(resolveAssetPath(status.imageUrl))
        setToast(`Image job failed (${status.errorCode ?? 'unknown'}).`)
        return
      }
      await sleep(700)
    }
    setToast('Image job timed out.')
  }

  async function submitCurrentMessage(): Promise<void> {
    const trimmed = input.trim()
    if (!trimmed || loading) return

    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setInput('')
    setLoading(true)
    setCompanionState('thinking')

    try {
      const bounds = chatPanelRef.current?.getBoundingClientRect()
      const imageWidth = bounds ? Math.round(bounds.width) : undefined
      const imageHeight = bounds ? Math.round(bounds.height) : undefined
      const turnPayload: ChatTurnRequest = {
        message: trimmed,
        includeOpenClaw,
      }
      if (imageWidth && imageHeight) {
        turnPayload.imageWidth = imageWidth
        turnPayload.imageHeight = imageHeight
      }

      const turn = await api<ChatTurnResponse>('/api/chat/turn', {
        method: 'POST',
        body: JSON.stringify(turnPayload),
      })

      setMessages((prev) => [...prev, { role: 'assistant', text: turn.replyText }])
      if (turn.warnings.length > 0) {
        setToast(turn.warnings[0])
      }
      await pollImage(turn.imageJobId, turn.emotion)
    } catch (error) {
      setCompanionState('frowning')
      setToast(error instanceof Error ? error.message : 'Turn failed.')
    } finally {
      setLoading(false)
    }
  }

  function handleSend(event: FormEvent): void {
    event.preventDefault()
    void submitCurrentMessage()
  }

  function handleComposerKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    void submitCurrentMessage()
  }

  async function saveSettings(): Promise<void> {
    const updated = await api<CompanionSettings>('/api/settings/companion', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
    setSettings(updated)
    setToast('Settings saved.')
  }

  async function uploadBaseImage(file: File | null): Promise<void> {
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    const updated = await api<CompanionSettings>('/api/settings/companion/base-image', {
      method: 'POST',
      body: formData,
    })
    setSettings(updated)
    setImageUrl(resolveBaseImagePreview(updated.baseImagePath))
    setToast('Base image uploaded.')
  }

  async function wipeMemory(): Promise<void> {
    await api('/api/memory', { method: 'DELETE' })
    await loadMemory(memoryQuery)
    setToast('Memory wiped.')
  }

  async function pollOpenClaw(): Promise<void> {
    const data = await api<OpenClawPollResponse>(
      `/api/openclaw/poll?cursor=${encodeURIComponent(openClawCursor)}`,
    )
    setOpenClawCursor(data.cursor)
    if (data.events.length === 0) return
    setOpenClawEvents((prev) => {
      const seen = new Set(prev.map((event) => `${event.requestId}|${event.ts}|${event.text}`))
      const merged = [...prev]
      for (const event of data.events) {
        const key = `${event.requestId}|${event.ts}|${event.text}`
        if (!seen.has(key)) {
          merged.push(event)
        }
      }
      return merged.slice(-25)
    })
  }

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">
        Skip to Main Content
      </a>
      <header className="top-bar">
        <div className="brand-block">
          <h1>Desktop Assistant</h1>
          <p>Realtime chat, image state, memory, and OpenClaw bridge in one workspace.</p>
        </div>
        <div className="controls-block">
          <p className="active-tab">Active View: {activeTabLabel}</p>
          <div className="tabs" role="tablist" aria-label="Assistant views">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'chat'}
              aria-controls="chat-panel"
              id="chat-tab"
              className={tab === 'chat' ? 'active' : ''}
              onClick={() => setTab('chat')}
            >
              Chat
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'settings'}
              aria-controls="settings-panel"
              id="settings-tab"
              className={tab === 'settings' ? 'active' : ''}
              onClick={() => setTab('settings')}
            >
              Settings
            </button>
          </div>
        </div>
      </header>

      {toast && (
        <div className="toast" role="status" aria-live="polite" aria-atomic="true">
          {toast}
        </div>
      )}

      <main id="main-content" className="workspace">
        <aside className={`companion-panel state-${companionState}`} aria-labelledby="companion-panel-title">
          <h2 id="companion-panel-title" className="panel-title">
            Companion
          </h2>
          <div className="state-pill">{stateLabel}</div>
          {imageUrl ? (
            <img
              src={imageUrl}
              alt="Companion portrait"
              className="companion-image"
              width={640}
              height={800}
              loading="lazy"
            />
          ) : (
            <div className="companion-placeholder">Base image not generated yet.</div>
          )}
          <p className="state-caption">
            Companion state reacts to reply emotion and moderation fallback.
          </p>
        </aside>

        {tab === 'chat' ? (
          <section
            id="chat-panel"
            aria-labelledby="chat-tab"
            ref={chatPanelRef}
            className="panel chat-panel"
          >
            <h2 className="panel-title">Chat Console</h2>
            <div className="messages" aria-label="Conversation history">
              {messages.map((message, index) => (
                <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
                  <p className="message-author">{message.role === 'assistant' ? 'Assistant' : 'You'}</p>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
            <form onSubmit={handleSend} className="composer">
              <label className="checkbox">
                <input
                  type="checkbox"
                  name="includeOpenClaw"
                  checked={includeOpenClaw}
                  onChange={(event) => setIncludeOpenClaw(event.target.checked)}
                />
                Send Turn to OpenClaw Bridge
              </label>
              <label className="field-label" htmlFor="chat-message-input">
                Message
              </label>
              <textarea
                id="chat-message-input"
                name="message"
                autoComplete="off"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder="Type a message…"
                rows={4}
              />
              <div className="row">
                <button type="submit" disabled={loading}>
                  {loading ? 'Processing…' : 'Send Turn'}
                </button>
                <button type="button" className="button-secondary" onClick={() => void pollOpenClaw()}>
                  Poll OpenClaw Events
                </button>
              </div>
            </form>
            <div className="openclaw-log">
              <h3>OpenClaw Timeline</h3>
              {openClawEvents.length === 0 ? (
                <p>No tagged events ingested yet.</p>
              ) : (
                <ul>
                  {openClawEvents.map((event, index) => (
                    <li key={`${event.requestId}-${event.ts}-${index}`}>
                      <strong>{event.requestId}</strong> {event.text}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        ) : (
          <section id="settings-panel" aria-labelledby="settings-tab" className="panel settings-panel">
            <h2 className="panel-title">Companion Settings</h2>
            <label htmlFor="bio-text">
              Bio
              <textarea
                id="bio-text"
                name="bio"
                autoComplete="off"
                value={settings.bio}
                onChange={(event) => setSettings((prev) => ({ ...prev, bio: event.target.value }))}
                rows={2}
              />
            </label>
            <label htmlFor="instructions-text">
              Instructions
              <textarea
                id="instructions-text"
                name="instructions"
                autoComplete="off"
                value={settings.instructions}
                onChange={(event) =>
                  setSettings((prev) => ({ ...prev, instructions: event.target.value }))
                }
                rows={3}
              />
            </label>
            <label htmlFor="base-image-file">
              Base image
              <input
                id="base-image-file"
                name="baseImageFile"
                type="file"
                accept="image/*"
                onChange={(event) => void uploadBaseImage(event.target.files?.[0] ?? null)}
              />
              <small>{settings.baseImagePath || 'No base image configured.'}</small>
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                name="nsfwEnabled"
                checked={settings.nsfwEnabled}
                onChange={(event) =>
                  setSettings((prev) => ({ ...prev, nsfwEnabled: event.target.checked }))
                }
              />
              NSFW Enabled
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                name="memoryEnabled"
                checked={settings.memoryEnabled}
                onChange={(event) =>
                  setSettings((prev) => ({ ...prev, memoryEnabled: event.target.checked }))
                }
              />
              Memory System Enabled
            </label>
            <div className="row">
              <button type="button" onClick={() => void saveSettings()}>
                Save Settings
              </button>
              <button
                type="button"
                className="button-secondary"
                onClick={() =>
                  void api('/api/memory/flush', {
                    method: 'POST',
                    body: JSON.stringify({ trigger: 'inactivity' }),
                  })
                }
              >
                Flush Memory
              </button>
            </div>
            <div className="memory-tools">
              <h3>Memory</h3>
              <div className="row">
                <label className="sr-only" htmlFor="memory-query-input">
                  Search Memory
                </label>
                <input
                  id="memory-query-input"
                  name="memoryQuery"
                  type="search"
                  autoComplete="off"
                  value={memoryQuery}
                  onChange={(event) => setMemoryQuery(event.target.value)}
                  placeholder="Search memory…"
                />
                <button type="button" className="button-secondary" onClick={() => void loadMemory(memoryQuery)}>
                  Query
                </button>
                <button type="button" className="button-danger" onClick={() => void wipeMemory()}>
                  Wipe
                </button>
              </div>
              {memoryItems.length === 0 ? (
                <p className="empty-state">No memory entries found.</p>
              ) : (
                <ul>
                  {memoryItems.map((item) => (
                    <li key={item.id}>
                      <strong>{item.category}</strong> {item.text}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

export default App
