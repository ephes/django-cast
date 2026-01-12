// podlove-player.ts
declare const podlovePlayer:
  | ((playerDiv: HTMLElement, url: string, configUrl: string) => void)
  | undefined;

let embedScriptPromise: Promise<void> | null = null;
let pageLoadPromise: Promise<void> | null = null;
let sharedObserver: IntersectionObserver | null = null;

const IDLE_CALLBACK_TIMEOUT_MS = 200;
const OBSERVER_ROOT_MARGIN = "200px 0px";
const CLICK_TO_LOAD_ATTR = "data-load-mode";
const CLICK_TO_LOAD_VALUE = "click";
const LOAD_BUTTON_TEXT = "Load player";
const LOAD_BUTTON_LOADING_TEXT = "Loading player...";
const LOAD_BUTTON_RETRY_TEXT = "Try again";
const LOAD_ERROR_TEXT = "Unable to load the audio player. Please try again.";

const EMBED_SCRIPT_ATTR = "data-podlove-embed";
const EMBED_SCRIPT_LOADED_ATTR = "data-podlove-embed-loaded";
const EMBED_SCRIPT_FAILED_ATTR = "data-podlove-embed-failed";

function waitForPageLoad(): Promise<void> {
  if (document.readyState === "complete") {
    return Promise.resolve();
  }

  if (!pageLoadPromise) {
    pageLoadPromise = new Promise((resolve) => {
      window.addEventListener("load", () => resolve(), { once: true });
    });
  }

  return pageLoadPromise;
}

function getSharedObserver(): IntersectionObserver {
  if (!sharedObserver) {
    sharedObserver = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }

          const target = entry.target;
          if (target instanceof PodlovePlayerElement) {
            target.scheduleInitialize();
          }

          observer.unobserve(target);
        });
      },
      { rootMargin: OBSERVER_ROOT_MARGIN }
    );
  }

  return sharedObserver;
}

function loadEmbedScript(embedUrl: string): Promise<void> {
  if (typeof podlovePlayer === "function") {
    return Promise.resolve();
  }

  if (embedScriptPromise) {
    return embedScriptPromise;
  }

  embedScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[${EMBED_SCRIPT_ATTR}]`);
    if (existing) {
      if (
        existing.getAttribute(EMBED_SCRIPT_LOADED_ATTR) === "true" &&
        typeof podlovePlayer === "function"
      ) {
        resolve();
        return;
      }
      if (existing.getAttribute(EMBED_SCRIPT_FAILED_ATTR) === "true") {
        existing.remove();
      } else {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener(
          "error",
          () => {
            existing.setAttribute(EMBED_SCRIPT_FAILED_ATTR, "true");
            existing.remove();
            embedScriptPromise = null;
            reject(new Error("Failed to load Podlove embed script"));
          },
          { once: true }
        );
        return;
      }
    }

    const script = document.createElement("script");
    script.src = embedUrl;
    script.async = true;
    script.setAttribute(EMBED_SCRIPT_ATTR, "true");
    script.addEventListener(
      "load",
      () => {
        script.setAttribute(EMBED_SCRIPT_LOADED_ATTR, "true");
        resolve();
      },
      { once: true }
    );
    script.addEventListener(
      "error",
      () => {
        script.setAttribute(EMBED_SCRIPT_FAILED_ATTR, "true");
        script.remove();
        embedScriptPromise = null;
        reject(new Error("Failed to load Podlove embed script"));
      },
      { once: true }
    );
    document.head.appendChild(script);
  });

  return embedScriptPromise;
}

function scheduleIdle(callback: () => void): number {
  if (typeof window.requestIdleCallback === "function") {
    return window.requestIdleCallback(() => callback(), { timeout: IDLE_CALLBACK_TIMEOUT_MS });
  }

  return window.setTimeout(() => callback(), 0);
}

function cancelIdle(handle: number): void {
  if (typeof window.cancelIdleCallback === "function") {
    window.cancelIdleCallback(handle);
    return;
  }

  window.clearTimeout(handle);
}

class PodlovePlayerElement extends HTMLElement {
  observer: IntersectionObserver | null;
  shadow: ShadowRoot;
  isInitialized: boolean;
  isScheduled: boolean;
  idleHandle: number | null;
  loadButton: HTMLButtonElement | null;
  clickHandler: (() => void) | null;
  errorMessage: HTMLParagraphElement | null;
  playerDiv: HTMLDivElement | null;

  constructor() {
    super();
    this.observer = null;
    this.isInitialized = false;
    this.isScheduled = false;
    this.idleHandle = null;
    this.loadButton = null;
    this.clickHandler = null;
    this.errorMessage = null;
    this.playerDiv = null;
    this.shadow = this.attachShadow({ mode: 'open' });
  }

  connectedCallback() {
    const clickToLoad = this.shouldClickToLoad();
    this.renderPlaceholder(clickToLoad);
    if (clickToLoad) {
      this.setupClickToLoad();
      return;
    }
    if (document.readyState === "complete") {
      this.observeElement();
      return;
    }

    waitForPageLoad().then(() => this.observeElement());
  }

  disconnectedCallback() {
    if (this.observer) {
      this.observer.unobserve(this);
    }

    if (this.loadButton && this.clickHandler) {
      this.loadButton.removeEventListener("click", this.clickHandler);
    }

    if (this.idleHandle !== null) {
      cancelIdle(this.idleHandle);
      this.idleHandle = null;
    }
  }

  shouldClickToLoad(): boolean {
    return this.getAttribute(CLICK_TO_LOAD_ATTR) === CLICK_TO_LOAD_VALUE;
  }

  renderPlaceholder(clickToLoad: boolean) {
    // Reserve space to prevent layout shifts
    const container = document.createElement('div');
    container.classList.add('podlove-player-container');
    if (clickToLoad) {
      container.classList.add('podlove-player-click-to-load');
    }

    // Apply styles
    const style = document.createElement('style');
    style.textContent = `
      .podlove-player-container {
        width: 100%;
        max-width: 936px;
        min-height: 300px;
        margin: 0 auto;
      }
      @media (max-width: 768px) {
        .podlove-player-container {
          max-width: 366px;
          min-height: 500px;
        }
      }
      .podlove-player-click-to-load {
        display: flex;
        flex-direction: column;
        gap: 0.8rem;
        align-items: center;
        justify-content: center;
        background: #f6f6f6;
        border: 1px solid #e3e3e3;
        border-radius: 8px;
      }
      .podlove-player-button {
        appearance: none;
        border: 1px solid #1a1a1a;
        background: #1a1a1a;
        color: #ffffff;
        border-radius: 999px;
        font-size: 0.95rem;
        padding: 0.6rem 1.4rem;
        cursor: pointer;
      }
      .podlove-player-button:focus-visible {
        outline: 3px solid #6aa5ff;
        outline-offset: 3px;
      }
      .podlove-player-button:disabled {
        opacity: 0.7;
        cursor: progress;
      }
      .podlove-player-error {
        margin: 1.2rem;
        color: #b42318;
        font-size: 0.95rem;
        text-align: center;
      }
      .podlove-player-container iframe {
        width: 100%;
        height: 100%;
        border: none;
      }
    `;

    this.shadow.appendChild(style);
    this.shadow.appendChild(container);

    const errorMessage = document.createElement("p");
    errorMessage.classList.add("podlove-player-error");
    errorMessage.hidden = true;
    errorMessage.setAttribute("role", "alert");
    errorMessage.textContent = LOAD_ERROR_TEXT;
    container.appendChild(errorMessage);
    this.errorMessage = errorMessage;

    if (clickToLoad) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = LOAD_BUTTON_TEXT;
      button.classList.add("podlove-player-button");
      button.setAttribute("aria-label", "Load audio player");
      container.appendChild(button);
      this.loadButton = button;
    }
  }

  observeElement() {
    this.observer = getSharedObserver();
    this.observer.observe(this);
  }

  setupClickToLoad() {
    if (!this.loadButton) {
      return;
    }

    this.clickHandler = () => {
      this.clearError();
      if (this.loadButton) {
        this.loadButton.disabled = true;
        this.loadButton.textContent = LOAD_BUTTON_LOADING_TEXT;
      }
      this.scheduleInitialize();
    };

    this.loadButton.addEventListener("click", this.clickHandler);
  }

  scheduleInitialize() {
    if (this.isInitialized || this.isScheduled) {
      return;
    }

    this.isScheduled = true;
    this.idleHandle = scheduleIdle(() => {
      this.idleHandle = null;
      this.isScheduled = false;
      this.initializePlayer();
    });
  }

  initializePlayer() {
    if (this.isInitialized) {
      return;
    }

    const container = this.shadow.querySelector('.podlove-player-container');
    if (!container) {
      return;
    }

    const url = this.getAttribute('data-url');
    if (!url) {
      return;
    }

    let audioId = this.getAttribute('id');
    if (!audioId) {
      audioId = `podlove-player-${Date.now()}`;
      this.setAttribute('id', audioId);
    }

    this.isInitialized = true;
    this.clearError();

    const configUrl = this.getAttribute('data-config') || '/api/audios/player_config/';
    const podloveTemplate = this.getAttribute('data-template');
    let embedUrl = this.getAttribute('data-embed') || 'https://cdn.podlove.org/web-player/5.x/embed.js';

    // If host ist localhost use local embed url
    const { hostname, port } = window.location;
    const playerDiv = this.getOrCreatePlayerDiv(container, audioId, podloveTemplate);

    if (typeof podlovePlayer === "function") {
      podlovePlayer(playerDiv, url, configUrl);
      this.finalizeLoad(container);
      return;
    }

    // If in dev mode on localhost and embedUrl starts with a slash, use the local embedUrl
    // otherwise the vite url 5173 will be used -> which will not work
    if (hostname === "localhost" && embedUrl.startsWith("/")) {
      embedUrl = `http://localhost:${port}${embedUrl}`;
    }

    loadEmbedScript(embedUrl)
      .then(() => {
        if (typeof podlovePlayer === "function") {
          podlovePlayer(playerDiv, url, configUrl);
          this.finalizeLoad(container);
          return;
        }
        this.handleLoadError();
      })
      .catch(() => {
        this.handleLoadError();
      });
  }

  getOrCreatePlayerDiv(container: Element, audioId: string, podloveTemplate: string | null) {
    if (!this.playerDiv) {
      this.playerDiv = document.createElement("div");
      this.playerDiv.classList.add("podlove-player-host");
    }

    if (!container.contains(this.playerDiv)) {
      container.appendChild(this.playerDiv);
    }

    this.playerDiv.id = audioId;

    if (podloveTemplate !== null) {
      this.playerDiv.setAttribute("data-template", podloveTemplate);
    } else {
      this.playerDiv.removeAttribute("data-template");
    }

    return this.playerDiv;
  }

  finalizeLoad(container: Element) {
    if (this.loadButton) {
      this.loadButton.remove();
      this.loadButton = null;
    }
    container.classList.remove("podlove-player-click-to-load");
    this.clearError();
  }

  clearError() {
    if (this.errorMessage) {
      this.errorMessage.hidden = true;
    }
  }

  handleLoadError() {
    this.isInitialized = false;
    if (this.errorMessage) {
      this.errorMessage.hidden = false;
    }
    if (this.loadButton) {
      this.loadButton.disabled = false;
      this.loadButton.textContent = LOAD_BUTTON_RETRY_TEXT;
    }
  }
}

customElements.define('podlove-player', PodlovePlayerElement);
