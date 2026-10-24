import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  getAccessToken,
  handleAuthCallback,
  logout,
  startLogin,
} from './auth'
import './App.css'

type Citation = {
  paper_id: string
  arxiv_url: string
  passage: string
}

type ConversationMessage = {
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
}

type ConversationCreateResponse = {
  conversation_id: string
}

type ConversationMessageResponse = {
  request_id: string
  conversation_id: string
  message: ConversationMessage
}

type ConversationResponse = {
  conversation_id: string
  messages: ConversationMessage[]
}

type ErrorResponse = {
  request_id?: string
  error?: {
    code?: string
    message?: string
  }
}

function App() {
  const [question, setQuestion] = useState(
    'What approaches improve transformer attention efficiency?',
  )
  const [maxPapers, setMaxPapers] = useState(5)
  const [accessToken, setAccessToken] = useState(() => getAccessToken() ?? '')
  const [conversationToRestore] = useState(
    () => sessionStorage.getItem('research_conversation_id') ?? '',
  )

  const [conversationId, setConversationId] = useState(
    conversationToRestore,
  )
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [authLoading, setAuthLoading] = useState(false)

  useEffect(() => {
    if (window.location.pathname !== '/auth/callback') {
      return
    }

    let cancelled = false

    async function completeLogin() {
      setAuthLoading(true)
      setError('')

      try {
        const token = await handleAuthCallback()

        if (cancelled) {
          return
        }

        setAccessToken(token)

        window.history.replaceState(
          {},
          document.title,
          '/',
        )
      } catch (authError) {
        if (cancelled) {
          return
        }

        setError(
          authError instanceof Error
            ? authError.message
            : 'Authentication failed.',
        )
      } finally {
        if (!cancelled) {
          setAuthLoading(false)
        }
      }
    }

    void completeLogin()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (
      !accessToken ||
      !conversationToRestore ||
      window.location.pathname === '/auth/callback'
    ) {
      return
    }

    let cancelled = false

    async function restoreConversation() {
      try {
        const response = await fetch(
          `/api/v1/conversations/${conversationToRestore}`,
          {
            headers: {
              Authorization: `Bearer ${accessToken}`,
            },
          },
        )

        if (!response.ok) {
          if (!cancelled && response.status === 404) {
            sessionStorage.removeItem('research_conversation_id')
            setConversationId('')
          }
          return
        }

        const body = (await response.json()) as ConversationResponse

        if (!cancelled) {
          setMessages(body.messages)
        }
      } catch {
        // Keep the app usable even if restoring prior history fails.
      }
    }

    void restoreConversation()

    return () => {
      cancelled = true
    }
  }, [accessToken, conversationToRestore])

  async function handleLogin() {
    setAuthLoading(true)
    setError('')

    try {
      await startLogin()
    } catch (authError) {
      setAuthLoading(false)
      setError(
        authError instanceof Error
          ? authError.message
          : 'Unable to start authentication.',
      )
    }
  }

  function handleLogout() {
    setAccessToken('')
    setConversationId('')
    setMessages([])
    sessionStorage.removeItem('research_conversation_id')
    logout()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const trimmedQuestion = question.trim()

    if (!trimmedQuestion) {
      setError('Enter a research question.')
      return
    }

    if (!accessToken) {
      setError('Sign in before starting research.')
      return
    }

    setLoading(true)
    setError('')

    try {
      let activeConversationId = conversationId

      if (!activeConversationId) {
        const createResponse = await fetch('/api/v1/conversations', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        })

        const createBody = (await createResponse.json()) as
          | ConversationCreateResponse
          | ErrorResponse

        if (!createResponse.ok) {
          const apiError = createBody as ErrorResponse
          throw new Error(
            apiError.error?.message ??
              `Conversation request failed with status ${createResponse.status}.`,
          )
        }

        activeConversationId = (
          createBody as ConversationCreateResponse
        ).conversation_id

        setConversationId(activeConversationId)
        sessionStorage.setItem(
          'research_conversation_id',
          activeConversationId,
        )
      }

      const userMessage: ConversationMessage = {
        role: 'user',
        content: trimmedQuestion,
        citations: [],
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        userMessage,
      ])

      const messageResponse = await fetch(
        `/api/v1/conversations/${activeConversationId}/messages`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: trimmedQuestion,
            max_papers: maxPapers,
          }),
        },
      )

      const messageBody = (await messageResponse.json()) as
        | ConversationMessageResponse
        | ErrorResponse

      if (!messageResponse.ok) {
        const apiError = messageBody as ErrorResponse
        throw new Error(
          apiError.error?.message ??
            `Research request failed with status ${messageResponse.status}.`,
        )
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        (messageBody as ConversationMessageResponse).message,
      ])

      setQuestion('')
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Research request failed.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <strong>arXiv Research Assistant</strong>
            <span>Evidence-grounded research synthesis</span>
          </div>
        </div>

        <div className="auth-controls">
          <div className="status-badge">
            <span className="status-dot" />
            Bedrock RAG
          </div>

          {accessToken ? (
            <button
              type="button"
              onClick={handleLogout}
              disabled={authLoading}
            >
              Logout
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleLogin()}
              disabled={authLoading}
            >
              {authLoading ? 'Signing in…' : 'Login'}
            </button>
          )}
        </div>
      </header>

      <main>
        <section className="hero-section">
          <p className="eyebrow">RESEARCH ACROSS THOUSANDS OF PAPERS</p>

          <h1>
            Ask research questions.
            <br />
            Get answers grounded in arXiv.
          </h1>

          <p className="hero-copy">
            Semantic retrieval, multi-paper synthesis, and validated citations
            powered by Amazon Bedrock.
          </p>

          <form className="research-form" onSubmit={handleSubmit}>
            <label htmlFor="question">Research question</label>

            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={4}
              maxLength={2000}
              placeholder="What does the research say about..."
            />

            <div className="form-row">
              <div className="paper-control">
                <label htmlFor="max-papers">Max papers</label>

                <select
                  id="max-papers"
                  value={maxPapers}
                  onChange={(event) =>
                    setMaxPapers(Number(event.target.value))
                  }
                >
                  {[3, 5, 7, 10].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={loading || authLoading || !accessToken}
              >
                {loading ? 'Researching…' : 'Research'}
              </button>
            </div>

            <div className="dev-auth">
              {accessToken ? (
                <p>Authenticated with Amazon Cognito.</p>
              ) : (
                <p>Sign in with Amazon Cognito to use the research assistant.</p>
              )}
            </div>
          </form>
        </section>

        {error && (
          <section className="error-card">
            <strong>Request failed</strong>
            <p>{error}</p>
          </section>
        )}

        {loading && (
          <section className="loading-card">
            <div className="spinner" />
            <div>
              <strong>Searching the research corpus</strong>
              <p>Retrieving evidence and synthesizing an answer…</p>
            </div>
          </section>
        )}

        {messages.length > 0 && (
          <section className="results">
            {messages.map((message, messageIndex) => (
              <div
                className={`answer-panel chat-message chat-message-${message.role}`}
                key={`${message.role}-${messageIndex}`}
              >
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">
                      {message.role === 'user' ? 'YOU' : 'RESEARCH ASSISTANT'}
                    </p>
                    <h2>
                      {message.role === 'user'
                        ? 'Research question'
                        : 'Research answer'}
                    </h2>
                  </div>

                  {message.role === 'assistant' && (
                    <span>
                      {message.citations.length}{' '}
                      {message.citations.length === 1 ? 'source' : 'sources'}
                    </span>
                  )}
                </div>

                <div className="answer-text">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>

                {message.role === 'assistant' &&
                  message.citations.length > 0 && (
                    <div className="citation-grid chat-citations">
                      {message.citations.map((citation, index) => (
                        <article
                          className="citation-card"
                          key={`${citation.paper_id}-${index}`}
                        >
                          <div className="citation-header">
                            <span>Source {index + 1}</span>
                            <strong>[{citation.paper_id}]</strong>
                          </div>

                          <p>{citation.passage}</p>

                          <a
                            href={citation.arxiv_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View paper on arXiv ↗
                          </a>
                        </article>
                      ))}
                    </div>
                  )}
              </div>
            ))}
          </section>
        )}
      </main>

      <footer>
        Built with FastAPI, Amazon Bedrock Knowledge Bases, and validated arXiv
        citations.
      </footer>
    </div>
  )
}

export default App
