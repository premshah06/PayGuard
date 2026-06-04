import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * useWebSocket — connects to a WebSocket URL and returns the message
 * history (newest-first, capped at 100) and connection status.
 *
 * Automatically reconnects every 3 seconds on disconnect.
 */
export function useWebSocket(url) {
  const [messages, setMessages] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (mountedRef.current) setConnected(true);
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 3_000);
      };

      ws.onerror = () => {
        ws.close();
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const msg = JSON.parse(event.data);
          setMessages(prev => [msg, ...prev].slice(0, 100));
        } catch {
          // Ignore malformed messages
        }
      };
    } catch {
      if (mountedRef.current) {
        reconnectTimer.current = setTimeout(connect, 3_000);
      }
    }
  }, [url]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { messages, connected };
}
