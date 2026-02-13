import { useEffect, useRef, useState, useCallback } from 'react';

interface PriceData {
  [tokenId: string]: number;
}

interface UsePriceWebSocketOptions {
  tokenIds: string[];
  enabled?: boolean;
}

interface UsePriceWebSocketReturn {
  prices: PriceData;
  isConnected: boolean;
  error: string | null;
}

export function usePriceWebSocket({
  tokenIds,
  enabled = true,
}: UsePriceWebSocketOptions): UsePriceWebSocketReturn {
  const [prices, setPrices] = useState<PriceData>({});
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!enabled || tokenIds.length === 0) return;

    // Determine WebSocket URL based on current location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = import.meta.env.VITE_API_URL
      ? new URL(import.meta.env.VITE_API_URL).host
      : window.location.host;
    const wsUrl = `${protocol}//${host}/ws/prices`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        console.log('[WS] Connected to price stream');

        // Subscribe to tokens
        ws.send(JSON.stringify({
          action: 'subscribe',
          token_ids: tokenIds,
        }));
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);

          if (message.type === 'prices') {
            setPrices((prev) => ({
              ...prev,
              ...message.data,
            }));
          } else if (message.type === 'subscribed') {
            console.log('[WS] Subscribed to tokens:', message.token_ids);
          } else if (message.type === 'error') {
            console.error('[WS] Error:', message.message);
            setError(message.message);
          }
        } catch (e) {
          console.error('[WS] Failed to parse message:', e);
        }
      };

      ws.onerror = (event) => {
        console.error('[WS] WebSocket error:', event);
        setError('WebSocket connection error');
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        console.log('[WS] Disconnected:', event.code, event.reason);

        // Attempt to reconnect after 2 seconds
        if (enabled) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('[WS] Attempting to reconnect...');
            connect();
          }, 2000);
        }
      };
    } catch (e) {
      console.error('[WS] Failed to create WebSocket:', e);
      setError('Failed to connect to WebSocket');
    }
  }, [enabled, tokenIds]);

  // Connect when enabled and tokenIds change
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  // Update subscriptions when tokenIds change
  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && tokenIds.length > 0) {
      wsRef.current.send(JSON.stringify({
        action: 'subscribe',
        token_ids: tokenIds,
      }));
    }
  }, [tokenIds]);

  return { prices, isConnected, error };
}

export default usePriceWebSocket;
