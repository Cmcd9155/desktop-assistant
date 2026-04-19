import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
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

  async function handleSend(event: FormEvent): Promise<void> {
    event.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || loading) return

    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setInput('')
    setLoading(true)
    setCompanionState('thinking')

    try {
      const turn = await api<ChatTurnResponse>('/api/chat/turn', {
        method: 'POST',
        body: JSON.stringify({ message: trimmed, includeOpenClaw }),
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
      <header className="top-bar">
        <h1>Desktop Assistant MVP1</h1>
        <div className="tabs">
          <button className={tab === 'chat' ? 'active' : ''} onClick={() => setTab('chat')}>
            Chat
          </button>
          <button className={tab === 'settings' ? 'active' : ''} onClick={() => setTab('settings')}>
            Settings
          </button>
        </div>
      </header>

      {toast && <div className="toast">{toast}</div>}

      <main className="workspace">
        <section className={`companion-panel state-${companionState}`}>
          <div className="state-pill">{stateLabel}</div>
          {imageUrl ? (
            <img src={imageUrl} alt="Companion" className="companion-image" />
          ) : (
            <div className="companion-placeholder">Base image not generated yet.</div>
          )}
          <p className="state-caption">
            Companion state reacts to reply emotion and moderation fallback.
          </p>
        </section>

        {tab === 'chat' ? (
          <section className="panel chat-panel">
            <div className="messages">
              {messages.map((message, index) => (
                <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
                  <h3>{message.role === 'assistant' ? 'Assistant' : 'You'}</h3>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
            <form onSubmit={handleSend} className="composer">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={includeOpenClaw}
                  onChange={(event) => setIncludeOpenClaw(event.target.checked)}
                />
                Send turn to OpenClaw bridge
              </label>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Type a message..."
                rows={4}
              />
              <div className="row">
                <button disabled={loading}>{loading ? 'Processing...' : 'Send Turn'}</button>
                <button type="button" onClick={() => void pollOpenClaw()}>
                  Poll OpenClaw
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
          <section className="panel settings-panel">
            <label>
              Bio
              <textarea
                value={settings.bio}
                onChange={(event) => setSettings((prev) => ({ ...prev, bio: event.target.value }))}
                rows={2}
              />
            </label>
            <label>
              Instructions
              <textarea
                value={settings.instructions}
                onChange={(event) =>
                  setSettings((prev) => ({ ...prev, instructions: event.target.value }))
                }
                rows={3}
              />
            </label>
            <label>
              Base image
              <input type="file" accept="image/*" onChange={(event) => void uploadBaseImage(event.target.files?.[0] ?? null)} />
              <small>{settings.baseImagePath || 'No base image configured.'}</small>
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={settings.nsfwEnabled}
                onChange={(event) =>
                  setSettings((prev) => ({ ...prev, nsfwEnabled: event.target.checked }))
                }
              />
              NSFW enabled
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={settings.memoryEnabled}
                onChange={(event) =>
                  setSettings((prev) => ({ ...prev, memoryEnabled: event.target.checked }))
                }
              />
              Memory system enabled
            </label>
            <div className="row">
              <button onClick={() => void saveSettings()}>Save Settings</button>
              <button
                type="button"
                onClick={() => void api('/api/memory/flush', { method: 'POST', body: JSON.stringify({ trigger: 'inactivity' }) })}
              >
                Flush Memory
              </button>
            </div>
            <div className="memory-tools">
              <h3>Memory</h3>
              <div className="row">
                <input
                  value={memoryQuery}
                  onChange={(event) => setMemoryQuery(event.target.value)}
                  placeholder="Search memory..."
                />
                <button onClick={() => void loadMemory(memoryQuery)}>Query</button>
                <button onClick={() => void wipeMemory()}>Wipe</button>
              </div>
              <ul>
                {memoryItems.map((item) => (
                  <li key={item.id}>
                    <strong>{item.category}</strong> {item.text}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

export default App
