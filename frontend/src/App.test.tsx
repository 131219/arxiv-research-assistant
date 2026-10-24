import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

beforeEach(() => {
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
  vi.restoreAllMocks()
})

describe('App', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.history.replaceState({}, '', '/')
  })

  it('renders the research assistant', () => {
    render(<App />)

    expect(
      screen.getByText('arXiv Research Assistant'),
    ).toBeInTheDocument()

    expect(
      screen.getByText(/Ask research questions/i),
    ).toBeInTheDocument()
  })
})

it('creates a conversation and renders the first assistant reply', async () => {
  sessionStorage.setItem('cognito_access_token', 'test-token')

  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          conversation_id: 'conv-123',
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
          },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          request_id: 'req-123',
          conversation_id: 'conv-123',
          message: {
            role: 'assistant',
            content: 'KV-cache compression reduces memory use [2606.03928].',
            citations: [
              {
                paper_id: '2606.03928',
                arxiv_url: 'https://arxiv.org/abs/2606.03928',
                passage: 'Relevant passage.',
              },
            ],
          },
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
          },
        },
      ),
    )

  const user = userEvent.setup()

  render(<App />)

  const textarea = screen.getByLabelText('Research question')

  await user.clear(textarea)
  await user.type(
    textarea,
    'Which methods improve long-context inference?',
  )

  await user.click(
    screen.getByRole('button', {
      name: 'Research',
    }),
  )

  expect(
    await screen.findByText(
      'Which methods improve long-context inference?',
    ),
  ).toBeInTheDocument()

  expect(
    await screen.findByText(
      'KV-cache compression reduces memory use [2606.03928].',
    ),
  ).toBeInTheDocument()

  expect(
    screen.getByText('[2606.03928]'),
  ).toBeInTheDocument()

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/api/v1/conversations',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer test-token',
      }),
    }),
  )

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/v1/conversations/conv-123/messages',
    expect.objectContaining({
      method: 'POST',
    }),
  )

  fetchMock.mockRestore()
})

it('reuses the same conversation for a follow-up question', async () => {
  sessionStorage.setItem('cognito_access_token', 'test-token')

  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          conversation_id: 'conv-123',
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
          },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          request_id: 'req-1',
          conversation_id: 'conv-123',
          message: {
            role: 'assistant',
            content: 'Sparse attention reduces attention cost [2606.11111].',
            citations: [
              {
                paper_id: '2606.11111',
                arxiv_url: 'https://arxiv.org/abs/2606.11111',
                passage: 'Sparse attention passage.',
              },
            ],
          },
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
          },
        },
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          request_id: 'req-2',
          conversation_id: 'conv-123',
          message: {
            role: 'assistant',
            content: 'KV-cache compression is useful for long-context inference [2606.03928].',
            citations: [
              {
                paper_id: '2606.03928',
                arxiv_url: 'https://arxiv.org/abs/2606.03928',
                passage: 'KV-cache compression passage.',
              },
            ],
          },
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
          },
        },
      ),
    )

  const user = userEvent.setup()

  render(<App />)

  const textarea = screen.getByLabelText('Research question')

  await user.clear(textarea)
  await user.type(
    textarea,
    'What approaches improve transformer attention efficiency?',
  )

  await user.click(
    screen.getByRole('button', {
      name: 'Research',
    }),
  )

  expect(
    await screen.findByText(
      'Sparse attention reduces attention cost [2606.11111].',
    ),
  ).toBeInTheDocument()

  await user.type(
    textarea,
    'Which of these works best for long-context inference?',
  )

  await user.click(
    screen.getByRole('button', {
      name: 'Research',
    }),
  )

  expect(
    await screen.findByText(
      'KV-cache compression is useful for long-context inference [2606.03928].',
    ),
  ).toBeInTheDocument()

  expect(fetchMock).toHaveBeenCalledTimes(3)

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/api/v1/conversations',
    expect.objectContaining({
      method: 'POST',
    }),
  )

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/v1/conversations/conv-123/messages',
    expect.objectContaining({
      method: 'POST',
    }),
  )

  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    '/api/v1/conversations/conv-123/messages',
    expect.objectContaining({
      method: 'POST',
    }),
  )

  fetchMock.mockRestore()
})

it('restores an existing conversation after refresh', async () => {
  sessionStorage.setItem('cognito_access_token', 'test-token')
  sessionStorage.setItem('research_conversation_id', 'conv-123')

  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          conversation_id: 'conv-123',
          messages: [
            {
              role: 'user',
              content: 'What approaches improve transformer attention efficiency?',
              citations: [],
            },
            {
              role: 'assistant',
              content: 'Sparse attention reduces computation [2606.11111].',
              citations: [
                {
                  paper_id: '2606.11111',
                  arxiv_url: 'https://arxiv.org/abs/2606.11111',
                  passage: 'Sparse attention passage.',
                },
              ],
            },
          ],
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
          },
        },
      ),
    )

  render(<App />)

  expect(
    await screen.findByText(
      'What approaches improve transformer attention efficiency?',
    ),
  ).toBeInTheDocument()

  expect(
    await screen.findByText(
      'Sparse attention reduces computation [2606.11111].',
    ),
  ).toBeInTheDocument()

  expect(fetchMock).toHaveBeenCalledOnce()

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/v1/conversations/conv-123',
    expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer test-token',
      }),
    }),
  )

  fetchMock.mockRestore()
})
