const cognitoDomain = import.meta.env.VITE_COGNITO_DOMAIN
const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID
const redirectUri = import.meta.env.VITE_COGNITO_REDIRECT_URI
const logoutUri = import.meta.env.VITE_COGNITO_LOGOUT_URI

const PKCE_VERIFIER_KEY = 'cognito_pkce_verifier'
const OAUTH_STATE_KEY = 'cognito_oauth_state'
const ACCESS_TOKEN_KEY = 'cognito_access_token'

type TokenResponse = {
  access_token: string
  id_token: string
  refresh_token?: string
  expires_in: number
  token_type: string
}

function requireConfig() {
  if (!cognitoDomain || !clientId || !redirectUri || !logoutUri) {
    throw new Error('Cognito frontend authentication is not configured.')
  }
}

function encodeBase64Url(bytes: Uint8Array): string {
  let binary = ''

  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }

  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

function randomString(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength)
  crypto.getRandomValues(bytes)
  return encodeBase64Url(bytes)
}

async function createCodeChallenge(verifier: string): Promise<string> {
  const encoded = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', encoded)

  return encodeBase64Url(new Uint8Array(digest))
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY)
}

export async function startLogin(): Promise<void> {
  requireConfig()

  const verifier = randomString(64)
  const challenge = await createCodeChallenge(verifier)
  const state = randomString(32)

  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier)
  sessionStorage.setItem(OAUTH_STATE_KEY, state)

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: 'openid email profile',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })

  window.location.assign(
    `https://${cognitoDomain}/oauth2/authorize?${params.toString()}`,
  )
}

async function exchangeAuthCallback(): Promise<string> {
  requireConfig()

  const params = new URLSearchParams(window.location.search)
  const code = params.get('code')
  const returnedState = params.get('state')
  const expectedState = sessionStorage.getItem(OAUTH_STATE_KEY)
  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY)

  if (!code || !returnedState || !expectedState || !verifier) {
    throw new Error('Invalid Cognito authentication callback.')
  }

  if (returnedState !== expectedState) {
    throw new Error('Invalid OAuth state.')
  }

  const response = await fetch(
    `https://${cognitoDomain}/oauth2/token`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: clientId,
        code,
        redirect_uri: redirectUri,
        code_verifier: verifier,
      }),
    },
  )

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(
      `Unable to exchange Cognito authorization code: ${response.status} ${errorText}`,
    )
  }

  const tokens = (await response.json()) as TokenResponse

  sessionStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
  sessionStorage.removeItem(PKCE_VERIFIER_KEY)
  sessionStorage.removeItem(OAUTH_STATE_KEY)

  return tokens.access_token
}

export function logout(): void {
  requireConfig()

  sessionStorage.removeItem(ACCESS_TOKEN_KEY)
  sessionStorage.removeItem(PKCE_VERIFIER_KEY)
  sessionStorage.removeItem(OAUTH_STATE_KEY)

  const params = new URLSearchParams({
    client_id: clientId,
    logout_uri: logoutUri,
  })

  window.location.assign(
    `https://${cognitoDomain}/logout?${params.toString()}`,
  )
}


let authCallbackPromise: Promise<string> | null = null

export function handleAuthCallback(): Promise<string> {
  if (!authCallbackPromise) {
    authCallbackPromise = exchangeAuthCallback()
  }

  return authCallbackPromise
}
