/**
 * Main desktop assistant UI.
 *
 * The frontend is intentionally small: it renders the companion view, sends chat
 * turns to the backend, polls long-running side effects like image generation
 * and OpenClaw ingestion, and exposes a settings/memory control panel.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
  // Let FormData set its own multipart boundary; JSON requests keep the explicit content type.
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
  // The backend returns app-relative static paths, while some callers may already have full URLs.
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_BASE}${url}`
}

function resolveBaseImagePreview(path: string | null | undefined): string {
  // Settings may store either an absolute filesystem path or an already-web-safe static path.
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
  // Keep the UI state explicit rather than deriving everything from server responses on each render.
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
  const companionFrameRef = useRef<HTMLDivElement | null>(null)
  const messagesContainerRef = useRef<HTMLDivElement | null>(null)
  const chatPanelRef = useRef<HTMLElement | null>(null)
  const activeTabLabel = tab === 'chat' ? 'Chat Console' : 'Companion Settings'

  // The visual state pill is presentation-only, so a memo keeps the transform colocated with its usage.
  const stateLabel = useMemo(() => companionState.toUpperCase(), [companionState])

  useEffect(() => {
    // Initial load hydrates settings and memory independently so one failure does not block the other.
    void loadSettings()
    void loadMemory()
  }, [])

  useEffect(() => {
    // Toasts are transient product feedback, not durable app state.
    if (!toast) return
    const timeout = setTimeout(() => setToast(''), 3500)
    return () => clearTimeout(timeout)
  }, [toast])

  useLayoutEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return
    container.scrollTop = container.scrollHeight
  }, [messages])

  async function loadSettings(): Promise<void> {
    // Settings also drive the base image preview, so refresh both together from one source of truth.
    const current = await api<CompanionSettings>('/api/settings/companion')
    setSettings({ ...current, nsfwEnabled: true })
    setImageUrl(resolveBaseImagePreview(current.baseImagePath))
  }

  async function loadMemory(query = ''): Promise<void> {
    // The backend owns filtering so the frontend can stay dumb about memory query semantics.
    const encoded = encodeURIComponent(query)
    const data = await api<{ items: MemoryItem[] }>(`/api/memory?query=${encoded}`)
    setMemoryItems(data.items)
  }

  async function pollImage(jobId: string, emotion: CompanionState): Promise<void> {
    // Image generation is asynchronous, so the UI polls until the job settles or times out.
    const deadline = Date.now() + 45_000
    while (Date.now() < deadline) {
      const status = await api<ChatImageResponse>(`/api/chat/image/${jobId}`)
      if (status.status === 'completed') {
        // On success, restore the emotion inferred from the text reply and swap in the new portrait.
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
        // Failures still keep the prior image visible if the backend supplied one.
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

    // Echo the user's turn locally immediately so the conversation feels responsive.
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setInput('')
    setLoading(true)
    setCompanionState('thinking')

    try {
      // The backend uses the visible chat panel size as a hint for portrait aspect ratio selection.
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

      // The text reply returns immediately; the companion portrait catches up via polling.
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
    // Enter sends by default, while Shift+Enter still allows multi-line prompts.
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    void submitCurrentMessage()
  }

  async function saveSettings(): Promise<void> {
    // Persist the whole settings object so frontend and backend stay in sync on one contract.
    const updated = await api<CompanionSettings>('/api/settings/companion', {
      method: 'PUT',
      body: JSON.stringify({ ...settings, nsfwEnabled: true }),
    })
    setSettings({ ...updated, nsfwEnabled: true })
    setToast('Settings saved.')
  }

  async function uploadBaseImage(file: File | null): Promise<void> {
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    // Uploading the base image also returns the updated settings payload, so we reuse it directly.
    const updated = await api<CompanionSettings>('/api/settings/companion/base-image', {
      method: 'POST',
      body: formData,
    })
    setSettings(updated)
    setImageUrl(resolveBaseImagePreview(updated.baseImagePath))
    setToast('Base image uploaded.')
  }

  async function wipeMemory(): Promise<void> {
    // After a destructive action, immediately refresh the visible list so there is no stale UI.
    await api('/api/memory', { method: 'DELETE' })
    await loadMemory(memoryQuery)
    setToast('Memory wiped.')
  }

  async function pollOpenClaw(): Promise<void> {
    // OpenClaw events are cursor-based, so repeated polling only fetches newer timeline entries.
    const data = await api<OpenClawPollResponse>(
      `/api/openclaw/poll?cursor=${encodeURIComponent(openClawCursor)}`,
    )
    setOpenClawCursor(data.cursor)
    if (data.events.length === 0) return
    setOpenClawEvents((prev) => {
      // Deduping protects against accidental repeated polls returning overlapping payloads.
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
      {/* Keyboard users can jump straight past the chrome to the active workspace. */}
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
        {/* The companion panel reflects the current image/emotion state regardless of active tab. */}
        <aside className={`companion-panel state-${companionState}`} aria-labelledby="companion-panel-title">
          <h2 id="companion-panel-title" className="panel-title">
            Companion
          </h2>
          <div className="state-pill">{stateLabel}</div>
          <div ref={companionFrameRef} className="companion-frame">
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
          </div>
          <p className="state-caption">
            Companion state reacts to reply emotion and moderation fallback.
          </p>
        </aside>

        {tab === 'chat' ? (
          <section
            id="chat-panel"
            ref={chatPanelRef}
            aria-labelledby="chat-tab"
            className="panel chat-panel"
          >
            <h2 className="panel-title">Chat Console</h2>
            <div ref={messagesContainerRef} className="messages" aria-label="Conversation history">
              {messages.map((message, index) => (
                <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
                  <p className="message-author">{message.role === 'assistant' ? 'Assistant' : 'You'}</p>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
            <form onSubmit={handleSend} className="composer">
              {/* OpenClaw is an optional sidecar; the primary chat loop still works without it. */}
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
                {/* Manual polling keeps the MVP simple without needing live sockets for the timeline. */}
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
            {/* These text fields shape the system prompt used by the backend chat agent. */}
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
              {/* The stored path is shown so local debugging is easier when anchors go missing. */}
              <small>{settings.baseImagePath || 'No base image configured.'}</small>
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
                  // Reuse the backend's flush endpoint instead of duplicating summarization logic in the UI.
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
                {/* Wipe is intentionally explicit and separate from query to avoid accidental deletion. */}
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
