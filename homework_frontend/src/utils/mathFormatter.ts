import katex from 'katex';

type Token =
  | { type: 'text'; content: string }
  | { type: 'math'; content: string; display: boolean };

const escapeHtml = (input: string) => {
  return (input || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
};

const renderTextHtml = (text: string) => {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\r?\n/g, '<br>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
};

/**
 * Convert LaTeX delimiters to a unified form:
 * - \\[ ... \\] → $$...$$ (display math)
 * - \\( ... \\) → $...$ (inline math)
 * Also handles LLM output quirks like backslash + newline + paren
 */
export const formatLatexDelimiters = (text: string): string => {
  if (!text) return '';

  return text
    // Handle LLM quirk: backslash + whitespace/newline + paren → proper delimiter
    .replace(/\\\s*\n\s*\[/g, '$$')
    .replace(/\\\s*\n\s*\]/g, '$$')
    .replace(/\\\s*\n\s*\(/g, '$')
    .replace(/\\\s*\n\s*\)/g, '$')
    .replace(/\\\[/g, '$$')
    .replace(/\\\]/g, '$$')
    .replace(/\\\(/g, '$')
    .replace(/\\\)/g, '$')
    .replace(/\\boldsymbol\{([^}]+)\}/g, '$1')
    .replace(/`+/g, '');
};

const tokenizeMath = (raw: string): Token[] => {
  const tokens: Token[] = [];
  const text = raw || '';
  let i = 0;

  const pushText = (start: number, end: number) => {
    if (end <= start) return;
    tokens.push({ type: 'text', content: text.slice(start, end) });
  };

  while (i < text.length) {
    const nextDollar = text.indexOf('$', i);
    if (nextDollar === -1) {
      pushText(i, text.length);
      break;
    }

    pushText(i, nextDollar);

    const isDouble = text.startsWith('$$', nextDollar);
    const openLen = isDouble ? 2 : 1;
    const close = isDouble ? '$$' : '$';
    const closeIdx = text.indexOf(close, nextDollar + openLen);

    if (closeIdx === -1) {
      tokens.push({ type: 'text', content: text.slice(nextDollar) });
      break;
    }

    const content = text.slice(nextDollar + openLen, closeIdx);
    tokens.push({ type: 'math', content, display: isDouble });
    i = closeIdx + openLen;
  }

  return tokens;
};

export const renderMathHtml = (text: string): string => {
  if (!text) return '';
  const formatted = formatLatexDelimiters(text);
  const tokens = tokenizeMath(formatted);

  return tokens
    .map((t) => {
      if (t.type === 'text') return renderTextHtml(t.content);
      const latex = (t.content || '').trim();
      if (!latex) return '';
      // Render with KaTeX
      const katexHtml = katex.renderToString(latex, {
        displayMode: t.display,
        throwOnError: false,
        strict: 'ignore',
        output: 'html',
      });
      // Wrap with a span that has red color class
      return `<span class="text-red-500 inline-flex items-center">${katexHtml}</span>`;
    })
    .join('');
};
