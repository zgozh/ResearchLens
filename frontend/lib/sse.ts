// SSE 客户端（§5.7 / §5.8）：POST + fetch + ReadableStream，
// 不是只能 GET 的 EventSource。解析 id/event/data 帧，JSON 在 data 行，
// 空行分隔，UTF-8 跨 chunk 解码，heartbeat 注释帧（':' 开头）忽略。

export interface SSEFrame {
  /** Last-Event-ID（job 事件重放用）。 */
  id: string | null;
  /** 自定义事件类型（不含 event: 行时为空）。 */
  event: string | null;
  /** data 字段原始文本（多行 data: 以 \n 连接）。 */
  data: string;
}

export interface OpenSSEOptions {
  method?: 'POST' | 'GET';
  body?: unknown;
  headers?: Record<string, string>;
  onEvent: (frame: SSEFrame) => void;
  /** 流正常结束（读到 done）时调用。 */
  onComplete?: () => void;
  signal?: AbortSignal;
}

interface FrameState {
  id: string | null;
  event: string | null;
  data: string[];
}

function makeState(): FrameState {
  return { id: null, event: null, data: [] };
}

/** 消费一行 SSE 文本，维护帧状态；遇到空行时返回该帧并重置。 */
function consumeLines(lines: string[], state: FrameState, onEvent: (f: SSEFrame) => void): void {
  for (const line of lines) {
    if (line === '') {
      if (state.data.length > 0) {
        onEvent({ id: state.id, event: state.event, data: state.data.join('\n') });
      }
      Object.assign(state, makeState());
      continue;
    }
    if (line.startsWith(':')) continue; // heartbeat 注释帧
    const colon = line.indexOf(':');
    let field: string;
    let value: string;
    if (colon === -1) {
      field = line;
      value = '';
    } else {
      field = line.slice(0, colon);
      value = line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
    }
    if (field === 'id') state.id = value;
    else if (field === 'event') state.event = value;
    else if (field === 'data') state.data.push(value);
    // retry 忽略
  }
}

/**
 * 打开 SSE 流并消费到结束。取消通过 AbortSignal；取消/网络错误会抛出（AbortError 等）。
 * 首个非 2xx 响应在建立流前以普通 HTTP 错误抛出。
 */
export async function openSSE(url: string, opts: OpenSSEOptions): Promise<void> {
  const { method = 'POST', body, headers, onEvent, onComplete, signal } = opts;

  const initHeaders: Record<string, string> = {
    Accept: 'text/event-stream',
    ...(body != null ? { 'Content-Type': 'application/json' } : {}),
    ...(headers || {}),
  };

  const res = await fetch(url, {
    method,
    cache: 'no-store',
    headers: initHeaders,
    body: body != null ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let message = `SSE ${res.status}`;
    try {
      const j = JSON.parse(text);
      if (j && typeof j === 'object') {
        message = (j as { detail?: string; message?: string }).detail
          ?? (j as { message?: string }).message
          ?? message;
      }
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }

  if (!res.body) throw new Error('响应无流 body');

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  const state = makeState();
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      consumeLines(lines, state, onEvent);
    }
    // flush 剩余解码
    buffer += decoder.decode();
    if (buffer.length > 0) {
      consumeLines(buffer.split('\n'), state, onEvent);
    }
  } finally {
    reader.releaseLock();
  }

  onComplete?.();
}

/** 解析 SSE 帧 data 中的 JSON。解析失败返回 null（调用方决定如何降级）。 */
export function parseSSEJson<T>(frame: SSEFrame): T | null {
  try {
    return JSON.parse(frame.data) as T;
  } catch {
    return null;
  }
}
