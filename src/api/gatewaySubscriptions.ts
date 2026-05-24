import { addGatewaySSEListener, ensureGatewaySSE } from './noetlClient';
import { getGatewayBaseUrl } from './gatewaySession';

export type DocumentData = Record<string, unknown>;
type Unsubscribe = () => void;

interface SubscriptionEvent {
  subscription_id?: string;
  doc_id?: string;
  data?: DocumentData;
  op?: 'added' | 'modified' | 'removed';
}

interface SubscribeOptions {
  signal?: AbortSignal;
  scope?: 'owner';
}

function sortByStartAt(items: DocumentData[]): DocumentData[] {
  return [...items].sort((left, right) => String(left.start_at || '').localeCompare(String(right.start_at || '')));
}

function parseSubscriptionEvent(message: unknown): SubscriptionEvent | undefined {
  const params = ((message as Record<string, unknown>)?.params || {}) as Record<string, unknown>;
  const op = String(params.op || '');
  if (op !== 'added' && op !== 'modified' && op !== 'removed') return undefined;
  const subscriptionId = String(params.subscription_id || '').trim();
  const docId = String(params.doc_id || '').trim();
  if (!subscriptionId || !docId) return undefined;
  return {
    subscription_id: subscriptionId,
    doc_id: docId,
    data: (params.data || {}) as DocumentData,
    op
  };
}

export function applySubscriptionEvent(
  current: Map<string, DocumentData>,
  event: SubscriptionEvent
): Map<string, DocumentData> {
  const next = new Map(current);
  const docId = String(event.doc_id || '').trim();
  if (!docId) return next;
  if (event.op === 'removed') {
    next.delete(docId);
    return next;
  }
  next.set(docId, { id: docId, ...(event.data || {}) });
  return next;
}

export function subscribeToCollection(
  path: string,
  onItems: (items: DocumentData[]) => void,
  options: SubscribeOptions = {}
): Unsubscribe {
  const controller = new AbortController();
  const sourceSignal = options.signal;
  let subscriptionId = '';
  let token = '';
  let closed = false;
  let docs = new Map<string, DocumentData>();
  let removeListener: Unsubscribe | undefined;

  const abort = () => {
    controller.abort();
  };
  sourceSignal?.addEventListener('abort', abort, { once: true });

  void (async () => {
    const connection = await ensureGatewaySSE(controller.signal);
    token = connection.token;
    const response = await fetch(`${getGatewayBaseUrl()}/api/subscriptions/firestore`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${connection.token}`
      },
      signal: controller.signal,
      body: JSON.stringify({
        path,
        scope: options.scope || 'owner',
        client_id: connection.clientId
      })
    });

    if (!response.ok) {
      throw new Error(`Gateway subscription failed (${response.status})`);
    }

    const payload = (await response.json()) as { subscription_id?: string };
    subscriptionId = String(payload.subscription_id || '');
    if (!subscriptionId) {
      throw new Error('Gateway subscription did not return a subscription id');
    }

    removeListener = addGatewaySSEListener('subscription/event', (event) => {
      const parsed = parseSubscriptionEvent(JSON.parse(event.data));
      if (!parsed || parsed.subscription_id !== subscriptionId) return;
      docs = applySubscriptionEvent(docs, parsed);
      onItems(Array.from(docs.values()));
    });
  })().catch((error) => {
    if (closed || (error instanceof DOMException && error.name === 'AbortError')) return;
    // The widget keeps its empty state; surfacing errors here would turn a live
    // update transport issue into a broken itinerary card.
    console.warn(error);
  });

  return () => {
    closed = true;
    sourceSignal?.removeEventListener('abort', abort);
    removeListener?.();
    controller.abort();
    if (subscriptionId && token) {
      void fetch(`${getGatewayBaseUrl()}/api/subscriptions/${encodeURIComponent(subscriptionId)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
        keepalive: true
      }).catch(() => undefined);
    }
  };
}

export function subscribeToCalendarEvents(path: string, onItems: (items: DocumentData[]) => void): Unsubscribe {
  return subscribeToCollection(path.replace(/^\/+/, ''), (items) => onItems(sortByStartAt(items)));
}
