import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const SAME_ORIGIN_URL_BASE = 'https://safe-relative.invalid/'
const SAME_ORIGIN_URL_ORIGIN = new URL(SAME_ORIGIN_URL_BASE).origin
const BACKSLASH_CHARACTER = String.fromCharCode(92)
const UNSAFE_URL_CONTROL_CHARACTER = /[\u0000-\u001f\u007f-\u009f]/

function safeLinkUrl(value) {
  if (typeof value !== 'string') return ''
  if (value.includes(BACKSLASH_CHARACTER) || UNSAFE_URL_CONTROL_CHARACTER.test(value)) return ''
  const url = value.trim()
  if (url.startsWith('#')) return url
  if (url.startsWith('/')) {
    if (url.startsWith('//')) return ''
    try {
      const parsed = new URL(url, SAME_ORIGIN_URL_BASE)
      return parsed.origin === SAME_ORIGIN_URL_ORIGIN ? url : ''
    } catch {
      return ''
    }
  }
  try {
    const parsed = new URL(url)
    if (parsed.username || parsed.password) return ''
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : ''
  } catch {
    return ''
  }
}

export function safeMarkdownUrlTransform(url, key) {
  if (key === 'src') return ''
  return key === 'href' ? safeLinkUrl(url) : ''
}

const SAFE_COMPONENTS = {
  img({ alt }) {
    return (
      <span className="blocked-markdown-image" role="note">
        {alt ? `[image blocked: ${alt}]` : '[image blocked]'}
      </span>
    )
  },
  a({ href, children }) {
    const safeHref = safeLinkUrl(href)
    if (!safeHref) return <span>{children}</span>
    const external = /^https?:\/\//i.test(safeHref)
    return (
      <a
        href={safeHref}
        {...(external
          ? {
              target: '_blank',
              rel: 'noopener noreferrer nofollow',
              referrerPolicy: 'no-referrer',
            }
          : {})}
      >
        {children}
      </a>
    )
  },
}

export default function SafeMarkdown({ children }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={SAFE_COMPONENTS}
      skipHtml
      urlTransform={safeMarkdownUrlTransform}
    >
      {typeof children === 'string' ? children : ''}
    </ReactMarkdown>
  )
}
