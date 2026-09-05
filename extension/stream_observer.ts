/**
 * OwlThread Chrome Extension - Manifest V3 Content Script
 * Module: ResilientStreamObserver
 *
 * Captures completed assistant turns from AI web chats (ChatGPT, Claude, DeepSeek)
 * with zero DOM mutations inside the observed container, dual-condition settlement
 * (1200ms debounce + stop button inactivity check), TreeWalker extraction,
 * FNV-1a fingerprinting, and MV3 port keep-alive heartbeats (20s).
 */

// ---------------------------------------------------------------------------
// Chrome Extension MV3 Port & Message Interfaces
// ---------------------------------------------------------------------------

declare namespace chrome.runtime {
  export interface Port {
    name: string;
    onDisconnect: {
      addListener: (callback: (port: Port) => void) => void;
      removeListener: (callback: (port: Port) => void) => void;
    };
    onMessage: {
      addListener: (callback: (message: any, port: Port) => void) => void;
      removeListener: (callback: (message: any, port: Port) => void) => void;
    };
    postMessage: (message: any) => void;
    disconnect: () => void;
  }

  export function connect(connectInfo?: { name?: string; includeTlsChannelId?: boolean }): Port;
  export function sendMessage(
    message: any,
    responseCallback?: (response: any) => void
  ): void;
  export const lastError: { message?: string } | undefined;
}

export type PlatformId = 'chatgpt' | 'claude' | 'deepseek' | 'generic';

export interface PlatformConfig {
  id: PlatformId;
  name: string;
  hostPatterns: string[];
  messageSelectors: string[];
  rootContainerSelectors: string[];
  activeIndicators: string[];
}

export interface ExtractedTurn {
  platform: PlatformId;
  role: 'assistant';
  text: string;
  fingerprint: string;
  url: string;
  title: string;
  timestamp: string;
  metadata: {
    turnIndex: number;
    containerType: string;
    wordCount: number;
    hostname: string;
  };
}

export interface PortMessage {
  type: 'heartbeat' | 'heartbeat_ack' | 'assistant_turn_captured' | 'ping';
  payload?: ExtractedTurn | Record<string, unknown>;
  timestamp: number;
}

export type TurnCallback = (turn: ExtractedTurn) => void;

// ---------------------------------------------------------------------------
// Platform Detection & Stable Semantic Selectors
// ---------------------------------------------------------------------------

export const PLATFORM_CONFIGS: Record<PlatformId, PlatformConfig> = {
  chatgpt: {
    id: 'chatgpt',
    name: 'ChatGPT',
    hostPatterns: ['chatgpt.com', 'chat.openai.com'],
    // Stable semantic containers for assistant messages (avoids obfuscated dynamic classes)
    messageSelectors: [
      '[data-message-author-role="assistant"]',
      'article [data-message-author-role="assistant"]',
      'div.agent-turn [data-message-author-role="assistant"]',
    ],
    rootContainerSelectors: ['main', 'div[role="presentation"]', 'body'],
    activeIndicators: [
      'button[data-testid="stop-button"]',
      'button[aria-label="Stop generating"]',
      'button[aria-label*="Stop"]',
    ],
  },
  claude: {
    id: 'claude',
    name: 'Claude',
    hostPatterns: ['claude.ai'],
    messageSelectors: [
      'div.font-claude-message',
      '[data-is-streaming]',
      'div[class*="font-claude-message"]',
      'div[data-test-render-count]',
    ],
    rootContainerSelectors: ['main', 'div.flex-1.overflow-y-auto', 'body'],
    activeIndicators: [
      'button[aria-label*="Stop"]',
      '[data-is-streaming="true"]',
      'button[data-testid="stop-button"]',
    ],
  },
  deepseek: {
    id: 'deepseek',
    name: 'DeepSeek',
    hostPatterns: ['deepseek.com', 'chat.deepseek.com'],
    messageSelectors: [
      'div.ds-markdown',
      'div[class*="ds-markdown"]',
      'div.chat-message[data-role="assistant"]',
    ],
    rootContainerSelectors: ['main', 'div#root', 'body'],
    activeIndicators: [
      '.ds-stop-button',
      '[aria-label*="Stop Generating"]',
      'button[aria-label*="Stop"]',
    ],
  },
  generic: {
    id: 'generic',
    name: 'Generic Web AI',
    hostPatterns: ['*'],
    messageSelectors: [
      '[data-message-author-role="assistant"]',
      '.chat-message.ai-msg',
      'article[data-role="assistant"]',
      'article',
    ],
    rootContainerSelectors: ['main', 'article', 'div[role="main"]', 'body'],
    activeIndicators: [
      'button[data-testid="stop-button"]',
      'button[aria-label*="Stop"]',
    ],
  },
};

// ---------------------------------------------------------------------------
// ResilientStreamObserver Class
// ---------------------------------------------------------------------------

export class ResilientStreamObserver {
  private readonly platform: PlatformConfig;
  private readonly debounceMs: number = 1200;
  private readonly heartbeatMs: number = 20000;
  private readonly portName: string = 'owlthread-port';

  private observer: MutationObserver | null = null;
  private debounceTimer: number | null = null;
  private observedContainer: Element | null = null;

  // MV3 Port & Keep-Alive State
  private port: chrome.runtime.Port | null = null;
  private heartbeatTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempts: number = 0;
  private isDestroyed: boolean = false;

  // De-duplication Cache
  private lastEmittedFingerprint: string | null = null;
  private readonly recentFingerprints: Set<string> = new Set<string>();
  private readonly maxFingerprintCacheSize: number = 50;

  // Optional local subscriber callback
  private turnSubscribers: TurnCallback[] = [];

  constructor(customDebounceMs: number = 1200) {
    this.debounceMs = customDebounceMs;
    this.platform = this.detectPlatform();
    console.log(`[OwlThread] Initialized ResilientStreamObserver for platform: ${this.platform.name} (${this.platform.id})`);
  }

  // -------------------------------------------------------------------------
  // 1. Target Detection & Multi-Platform Support
  // -------------------------------------------------------------------------

  public detectPlatform(): PlatformConfig {
    const currentHost = window.location.hostname.toLowerCase();

    for (const key of ['chatgpt', 'claude', 'deepseek'] as PlatformId[]) {
      const config = PLATFORM_CONFIGS[key];
      if (config.hostPatterns.some(pattern => currentHost.includes(pattern))) {
        return config;
      }
    }

    return PLATFORM_CONFIGS.generic;
  }

  public getPlatformConfig(): PlatformConfig {
    return this.platform;
  }

  // -------------------------------------------------------------------------
  // 2. Lifecycle: Start, Attach, Disconnect
  // -------------------------------------------------------------------------

  public start(): void {
    if (this.isDestroyed) {
      console.warn('[OwlThread] ResilientStreamObserver is destroyed. Call restart() instead.');
      return;
    }

    // Connect MV3 port with keep-alive heartbeat
    this.connectPort();

    // Attach MutationObserver without polling
    this.attachObserver();
  }

  public destroy(): void {
    this.isDestroyed = true;

    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }

    if (this.debounceTimer !== null) {
      window.clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }

    this.stopHeartbeat();

    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.port) {
      try {
        this.port.disconnect();
      } catch (e) {}
      this.port = null;
    }

    this.observedContainer = null;
    this.turnSubscribers = [];
    console.log('[OwlThread] ResilientStreamObserver destroyed.');
  }

  public onTurnExtracted(callback: TurnCallback): () => void {
    this.turnSubscribers.push(callback);
    return () => {
      this.turnSubscribers = this.turnSubscribers.filter(cb => cb !== callback);
    };
  }

  // -------------------------------------------------------------------------
  // 3. Event-Driven MutationObserver (Zero DOM Mutations Inside Container)
  // -------------------------------------------------------------------------

  private attachObserver(): void {
    const targetElement = this.locateSemanticContainer();
    if (!targetElement) {
      // If root container is not rendered yet, watch documentElement until container appears
      this.waitForContainer();
      return;
    }

    this.observedContainer = targetElement;

    // Observe child additions, text changes, and subtree modifications
    this.observer = new MutationObserver((mutations: MutationRecord[]) => {
      this.handleMutations(mutations);
    });

    this.observer.observe(targetElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    console.log(`[OwlThread] Observer successfully attached to container: <${targetElement.tagName.toLowerCase()}>`);
  }

  private waitForContainer(): void {
    const docObserver = new MutationObserver((_, obs) => {
      const el = this.locateSemanticContainer();
      if (el) {
        obs.disconnect();
        this.attachObserver();
      }
    });

    docObserver.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }

  private locateSemanticContainer(): Element | null {
    for (const selector of this.platform.rootContainerSelectors) {
      const el = document.querySelector(selector);
      if (el) {
        return el;
      }
    }
    return document.body;
  }

  private handleMutations(mutations: MutationRecord[]): void {
    // Check if mutations were caused by extension Shadow DOM host; ignore to prevent loops
    const onlyExtensionMutations = mutations.every(m => {
      const target = m.target as HTMLElement;
      return target && (target.id === 'owlthread-shadow-host' || target.closest?.('#owlthread-shadow-host'));
    });

    if (onlyExtensionMutations) {
      return;
    }

    // Trailing-edge debounce timer reset
    if (this.debounceTimer !== null) {
      window.clearTimeout(this.debounceTimer);
    }

    this.debounceTimer = window.setTimeout(() => {
      this.debounceTimer = null;
      this.evaluateSettlement();
    }, this.debounceMs);
  }

  // -------------------------------------------------------------------------
  // 4. Dual-Condition Settlement Detection
  // -------------------------------------------------------------------------

  /**
   * Dual-condition verification:
   * 1. Check if generation is actively ongoing (stop buttons or streaming tags).
   * 2. If active, re-arm the debounce timer.
   * 3. If inactive and 1200ms quiet window has passed, finalize turn extraction.
   */
  public evaluateSettlement(): void {
    if (this.isDestroyed) return;

    if (this.isGenerationActive()) {
      // Re-arm debounce timer since stream is actively writing tokens
      this.debounceTimer = window.setTimeout(() => {
        this.debounceTimer = null;
        this.evaluateSettlement();
      }, this.debounceMs);
      return;
    }

    // Generation is inactive and 1200ms has elapsed with no mutations -> Settle!
    this.settleCompletedTurn();
  }

  public isGenerationActive(): boolean {
    for (const indicator of this.platform.activeIndicators) {
      const elements = document.querySelectorAll(indicator);
      for (let i = 0; i < elements.length; i++) {
        const el = elements[i] as HTMLElement;
        // Verify element is rendered in layout and visible
        if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0)) {
          return true;
        }
      }
    }
    return false;
  }

  private settleCompletedTurn(): void {
    const assistantNodes = this.locateAssistantTurnNodes();
    if (!assistantNodes || assistantNodes.length === 0) {
      return;
    }

    // Target the most recent assistant message node
    const lastNode = assistantNodes[assistantNodes.length - 1];
    const turnIndex = assistantNodes.length;

    const rawCleanText = this.extractCleanText(lastNode);
    if (!rawCleanText || rawCleanText.trim().length < 5) {
      return;
    }

    // -----------------------------------------------------------------------
    // 5. De-duplication & Fingerprinting
    // -----------------------------------------------------------------------
    const fingerprint = this.computeFingerprint(rawCleanText);

    if (this.recentFingerprints.has(fingerprint)) {
      // Already emitted this exact turn payload; ignore re-renders
      return;
    }

    this.recordFingerprint(fingerprint);
    this.lastEmittedFingerprint = fingerprint;

    const words = rawCleanText.split(/\s+/).filter(Boolean);
    const turn: ExtractedTurn = {
      platform: this.platform.id,
      role: 'assistant',
      text: rawCleanText,
      fingerprint,
      url: window.location.href,
      title: document.title || 'AI Chat',
      timestamp: new Date().toISOString(),
      metadata: {
        turnIndex,
        containerType: lastNode.tagName.toLowerCase(),
        wordCount: words.length,
        hostname: window.location.hostname,
      },
    };

    // Emit turn via port and notify subscribers
    this.emitTurn(turn);
  }

  private locateAssistantTurnNodes(): Element[] {
    const results: Element[] = [];

    for (const selector of this.platform.messageSelectors) {
      const nodes = document.querySelectorAll(selector);
      if (nodes.length > 0) {
        nodes.forEach(node => {
          // Avoid grabbing nested elements matching the same selector
          if (!results.some(existing => existing.contains(node))) {
            results.push(node);
          }
        });
        break; // Use the most specific matched selector
      }
    }

    return results;
  }

  // -------------------------------------------------------------------------
  // 6. Clean Text Extraction (TreeWalker)
  // -------------------------------------------------------------------------

  /**
   * Extracts visible, human-readable text from the node tree using TreeWalker.
   * Explicitly strips buttons, svg icons, style, script, and elements with aria-hidden="true".
   */
  public extractCleanText(rootNode: Node): string {
    const filter: NodeFilter = {
      acceptNode: (node: Node): number => {
        const parent = node.parentElement;
        if (!parent) {
          return NodeFilter.FILTER_REJECT;
        }

        // 1. Strip non-content and interactive noise tags
        const tagName = parent.tagName.toUpperCase();
        if (
          tagName === 'BUTTON' ||
          tagName === 'SVG' ||
          tagName === 'STYLE' ||
          tagName === 'SCRIPT' ||
          tagName === 'NOSCRIPT' ||
          tagName === 'IFRAME' ||
          tagName === 'CANVAS' ||
          tagName === 'AUDIO' ||
          tagName === 'VIDEO'
        ) {
          return NodeFilter.FILTER_REJECT;
        }

        // 2. Strip action bars, copy buttons, tooltips with aria-hidden="true"
        if (parent.closest('[aria-hidden="true"]')) {
          return NodeFilter.FILTER_REJECT;
        }

        // 3. Strip extension UI elements
        if (parent.closest('#owlthread-shadow-host') || parent.closest('[data-owlthread-ignore]')) {
          return NodeFilter.FILTER_REJECT;
        }

        // 4. Reject empty or pure whitespace text nodes
        const textVal = node.nodeValue;
        if (!textVal || !textVal.trim()) {
          return NodeFilter.FILTER_SKIP;
        }

        return NodeFilter.FILTER_ACCEPT;
      },
    };

    const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT, filter);
    const textChunks: string[] = [];
    let current: Node | null = walker.nextNode();

    while (current) {
      if (current.nodeValue) {
        textChunks.push(current.nodeValue);
      }
      current = walker.nextNode();
    }

    return this.normalizeWhitespace(textChunks.join(' '));
  }

  private normalizeWhitespace(raw: string): string {
    return raw
      .replace(/[	]+/g, ' ')
      .replace(/ +/g, ' ')
      .replace(/
\s*
\s*
+/g, '

')
      .trim();
  }

  // -------------------------------------------------------------------------
  // 7. FNV-1a Quick Fingerprinting & Deduplication
  // -------------------------------------------------------------------------

  public computeFingerprint(text: string): string {
    let hash = 0x811c9dc5; // 32-bit FNV offset basis
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193); // 32-bit FNV prime
    }
    const hex = (hash >>> 0).toString(16).padStart(8, '0');
    return `fnv1a-${hex}-len${text.length}`;
  }

  private recordFingerprint(fp: string): void {
    this.recentFingerprints.add(fp);
    if (this.recentFingerprints.size > this.maxFingerprintCacheSize) {
      const oldest = this.recentFingerprints.values().next().value;
      if (oldest) {
        this.recentFingerprints.delete(oldest);
      }
    }
  }

  // -------------------------------------------------------------------------
  // 8. MV3 Port Lifecycle & Keep-Alive Heartbeat
  // -------------------------------------------------------------------------

  public connectPort(): void {
    if (this.isDestroyed) return;

    try {
      this.cleanupPort();

      // Connect to background service worker via Manifest V3 Port
      this.port = chrome.runtime.connect({ name: this.portName });
      this.reconnectAttempts = 0;

      this.port.onDisconnect.addListener(() => {
        console.warn('[OwlThread] MV3 Port disconnected from background service worker.');
        this.handlePortDisconnect();
      });

      this.port.onMessage.addListener((message: any) => {
        if (message && message.type === 'heartbeat_ack') {
          // Keep-alive heartbeat acknowledged by background service worker
        }
      });

      // Start 20s keep-alive heartbeat
      this.startHeartbeat();
      console.log(`[OwlThread] Connected to MV3 Port: "${this.portName}" (Heartbeat: 20s)`);
    } catch (err) {
      console.warn('[OwlThread] Failed connecting to MV3 port:', err);
      this.schedulePortReconnect();
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      this.sendHeartbeat();
    }, this.heartbeatMs);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private sendHeartbeat(): void {
    if (!this.port) return;

    try {
      this.port.postMessage({
        type: 'heartbeat',
        timestamp: Date.now(),
      });
    } catch (err) {
      console.warn('[OwlThread] Heartbeat delivery error, resetting port:', err);
      this.handlePortDisconnect();
    }
  }

  private handlePortDisconnect(): void {
    this.cleanupPort();
    if (!this.isDestroyed) {
      this.schedulePortReconnect();
    }
  }

  private schedulePortReconnect(): void {
    if (this.reconnectTimer !== null || this.isDestroyed) return;

    // Exponential backoff: 1s, 1.5s, 2.25s, ... capped at 10s
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 10000);
    this.reconnectAttempts++;

    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.isDestroyed) {
        this.connectPort();
      }
    }, delay);
  }

  private cleanupPort(): void {
    this.stopHeartbeat();
    if (this.port) {
      try {
        this.port.disconnect();
      } catch (e) {}
      this.port = null;
    }
  }

  // -------------------------------------------------------------------------
  // 9. Turn Emission to Background Service Worker
  // -------------------------------------------------------------------------

  public emitTurn(turn: ExtractedTurn): void {
    // 1. Notify any in-page subscribers
    for (const subscriber of this.turnSubscribers) {
      try {
        subscriber(turn);
      } catch (err) {
        console.error('[OwlThread] Turn subscriber error:', err);
      }
    }

    // 2. Post over persistent MV3 Port if connected
    if (this.port) {
      try {
        this.port.postMessage({
          type: 'assistant_turn_captured',
          payload: turn,
          timestamp: Date.now(),
        });
        console.log(`[OwlThread] Captured assistant turn [${turn.platform}] (${turn.metadata.wordCount} words) emitted over port.`);
        return;
      } catch (err) {
        console.warn('[OwlThread] Failed to post message over port, falling back to runtime.sendMessage:', err);
      }
    }

    // 3. Fallback to standard one-shot runtime message
    try {
      chrome.runtime.sendMessage({
        action: 'send_capture',
        payload: {
          text: turn.text,
          source_app: `web_${turn.platform}`,
          url: turn.url,
          title: turn.title,
          containerType: 'assistant_turn',
          metadata: {
            fingerprint: turn.fingerprint,
            platform: turn.platform,
            turnIndex: turn.metadata.turnIndex,
            captured_at: turn.timestamp,
          },
        },
      });
      console.log(`[OwlThread] Captured assistant turn [${turn.platform}] emitted via fallback sendMessage.`);
    } catch (err) {
      console.error('[OwlThread] Error sending capture to background script:', err);
    }
  }
}
