import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import SafeMarkdown, { safeMarkdownUrlTransform } from './SafeMarkdown'

const BROWSER_BASE = 'https://council.example/app/'

describe('SafeMarkdown', () => {
  it.each(['final answer', 'stage response', 'stage verdict', 'dissent'])(
    'blocks remote image loading in %s content',
    () => {
      const markup = renderToStaticMarkup(
        <SafeMarkdown>
          {'![tracking](https://example.invalid/pixel?synthetic=private)'}
        </SafeMarkdown>,
      )

      expect(markup).not.toContain('<img')
      expect(markup).not.toContain('example.invalid')
      expect(markup).not.toContain('synthetic=private')
      expect(markup).toContain('[image blocked: tracking]')
    },
  )

  it('hardens external links and rejects active or protocol-relative URLs', () => {
    const markup = renderToStaticMarkup(
      <SafeMarkdown>
        {'[safe](https://example.com/page) [script](javascript:alert(1)) [remote](//example.invalid/x)'}
      </SafeMarkdown>,
    )

    expect(markup).toContain('href="https://example.com/page"')
    expect(markup).toContain('rel="noopener noreferrer nofollow"')
    expect(markup).toContain('referrerPolicy="no-referrer"')
    expect(markup).not.toContain('javascript:')
    expect(markup).not.toContain('example.invalid')
  })

  it.each([
    String.raw`/\cross-origin.example/path`,
    '/\t/cross-origin.example/path',
    '/\n/cross-origin.example/path',
    '/\r/cross-origin.example/path',
  ])('rejects root-like URL %j that browsers normalize across origins', (url) => {
    expect(new URL(url, BROWSER_BASE).origin).not.toBe(
      new URL(BROWSER_BASE).origin,
    )
    expect(safeMarkdownUrlTransform(url, 'href')).toBe('')
  })

  it('keeps Markdown-encoded backslash paths same-origin', () => {
    const markup = renderToStaticMarkup(
      <SafeMarkdown>{String.raw`[unsafe](/\cross-origin.example/path)`}</SafeMarkdown>,
    )
    const href = markup.match(/href="([^"]+)"/)?.[1]

    expect(href).toBe('/%5Ccross-origin.example/path')
    expect(new URL(href, BROWSER_BASE).origin).toBe(new URL(BROWSER_BASE).origin)
  })

  it.each([
    String.raw`/docs\chapter`,
    `/docs${String.fromCharCode(0)}chapter`,
    `/docs${String.fromCharCode(127)}chapter`,
  ])('rejects relative URL %j containing unsafe URL characters', (url) => {
    expect(safeMarkdownUrlTransform(url, 'href')).toBe('')
  })

  it.each(['/docs', '/docs/getting-started?mode=safe#install', '#install'])(
    'preserves safe same-origin URL %s',
    (url) => {
      expect(new URL(url, BROWSER_BASE).origin).toBe(new URL(BROWSER_BASE).origin)
      expect(safeMarkdownUrlTransform(url, 'href')).toBe(url)
    },
  )

  it.each([
    'http:example.com/path',
    'http:/example.com/path',
    'https:example.com/path',
    'https:/example.com/path',
  ])('canonicalizes and hardens nonstandard external URL form %s', (url) => {
    const markup = renderToStaticMarkup(
      <SafeMarkdown>{`[external](${url})`}</SafeMarkdown>,
    )

    expect(markup).toContain('target="_blank"')
    expect(markup).toContain('rel="noopener noreferrer nofollow"')
    expect(markup).toContain('referrerPolicy="no-referrer"')
  })

  it('rejects links containing URL userinfo', () => {
    const credentialUrl =
      'https://user' + String.fromCharCode(58) + 'password@example.com/path'
    const markup = renderToStaticMarkup(
      <SafeMarkdown>
        {`[credential](${credentialUrl})`}
      </SafeMarkdown>,
    )

    expect(markup).not.toContain('href=')
    expect(markup).not.toContain('user:password')
  })

  it('does not enable raw HTML', () => {
    const markup = renderToStaticMarkup(
      <SafeMarkdown>
        {'<img src="https://example.invalid/raw-pixel">safe text'}
      </SafeMarkdown>,
    )

    expect(markup).not.toContain('<img')
    expect(markup).not.toContain('example.invalid')
    expect(markup).toContain('safe text')
  })
})
