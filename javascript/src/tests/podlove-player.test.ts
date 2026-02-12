import { describe, it, expect, beforeEach, vi } from 'vitest';

// podlove-player.test.js
import '@testing-library/jest-dom';

// Import the component code
import '@/audio/podlove-player';


class IntersectionObserverMock {
  callback: IntersectionObserverCallback;
  observedElements: Set<Element>;
  options?: IntersectionObserverInit;

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback;
    this.observedElements = new Set<Element>();
    this.options = options;
  }

  observe(target: Element) {
    this.observedElements.add(target);
  }

  unobserve(target: Element) {
    this.observedElements.delete(target);
  }

  disconnect() {
    this.observedElements.clear();
  }

  // Method to simulate intersection events
  trigger(entries: IntersectionObserverEntry[]) {
    const observedEntries = entries.filter(entry => this.observedElements.has(entry.target));
    if (observedEntries.length > 0) {
      this.callback(observedEntries, this);
    }
  }
}

globalThis.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver;

// Mock the podlovePlayer function
global.podlovePlayer = vi.fn();

describe('PodlovePlayerElement', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.documentElement.removeAttribute('data-bs-theme');
    document.documentElement.removeAttribute('data-theme');
    document.body.removeAttribute('data-bs-theme');
    document.body.removeAttribute('data-theme');
    global.podlovePlayer.mockReset();
    globalThis.matchMedia = vi.fn().mockImplementation(() => ({
      matches: false,
      media: '',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    globalThis.requestIdleCallback = vi.fn((callback: IdleRequestCallback) => {
      callback({ didTimeout: false, timeRemaining: () => 50 });
      return 1;
    });
    globalThis.cancelIdleCallback = vi.fn();
  });

  const setupAndTrigger = (configUrl?: string) => {
    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    if (configUrl) {
      element.setAttribute('data-config', configUrl);
    }
    document.body.appendChild(element);

    const observerInstance = element.observer as IntersectionObserverMock;
    observerInstance.trigger([
      { isIntersecting: true, target: element } as IntersectionObserverEntry,
    ]);

    return element.querySelector('.podlove-player-host') as HTMLDivElement | null;
  };

  it('should define the custom element', () => {
    expect(customElements.get('podlove-player')).toBeDefined();
  });

  it('should render the placeholder container', () => {
    const element = document.createElement('podlove-player');
    document.body.appendChild(element);

    const container = element.querySelector('.podlove-player-container');
    expect(container).not.toBeNull();
  });

  it('should read the id and data-url attributes', () => {
    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    document.body.appendChild(element);

    expect(element.getAttribute('id')).toBe('audio_63');
    expect(element.getAttribute('data-url')).toBe('/api/audios/podlove/63/post/75/');
  });

  it('should set up an IntersectionObserver', () => {
    const observeSpy = vi.spyOn(IntersectionObserver.prototype, 'observe');
    const element = document.createElement('podlove-player');
    document.body.appendChild(element);

    expect(observeSpy).toHaveBeenCalledWith(element);
    observeSpy.mockRestore();
  });

  it('should use a shared observer with a root margin', () => {
    const element = document.createElement('podlove-player');
    document.body.appendChild(element);

    const observerInstance = element.observer as IntersectionObserverMock;
    expect(observerInstance.options?.rootMargin).toBe('200px 0px');
  });

  it('should initialize the player when in view', () => {
    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    document.body.appendChild(element);

    // Access the observer
    const observerInstance = element.observer;

    // Simulate the IntersectionObserver callback
    const entries = [{ isIntersecting: true, target: element }];
    observerInstance.callback(entries, observerInstance);

    // Check that podlovePlayer was called
    const playerHost = element.querySelector('.podlove-player-host') as HTMLDivElement | null;
    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/'
    );
  });

  it('should release reserved min-height after successful load', () => {
    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    document.body.appendChild(element);

    const container = element.querySelector('.podlove-player-container') as HTMLDivElement | null;
    expect(container).not.toBeNull();
    expect(container?.style.minHeight).toBe('');
    expect(element.style.minHeight).toBe('');

    const observerInstance = element.observer as IntersectionObserverMock;
    observerInstance.trigger([
      { isIntersecting: true, target: element } as IntersectionObserverEntry,
    ]);

    expect(container?.style.minHeight).toBe('auto');
    expect(element.style.minHeight).toBe('auto');
  });

  it('should inject dark loading styles to avoid iframe white flashes', () => {
    const element = document.createElement('podlove-player');
    document.body.appendChild(element);

    const style = document.getElementById('podlove-player-styles');
    expect(style).not.toBeNull();
    expect(style?.textContent).toContain('color-scheme: dark');
    expect(style?.textContent).toContain('background-color: #1e293b');
  });

  it('should append dark color_scheme when document theme is dark', () => {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
    const playerHost = setupAndTrigger();

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?color_scheme=dark'
    );
  });

  it('should append dark color_scheme with query params and hash fragments', () => {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
    const playerHost = setupAndTrigger('/api/audios/player_config/?foo=bar#fragment');

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?foo=bar&color_scheme=dark#fragment'
    );
  });

  it('should append dark color_scheme for hash-only config urls', () => {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
    const playerHost = setupAndTrigger('/api/audios/player_config/#fragment');

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?color_scheme=dark#fragment'
    );
  });

  it('should not overwrite an explicit color_scheme query parameter', () => {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
    const playerHost = setupAndTrigger('/api/audios/player_config/?color_scheme=light');

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?color_scheme=light'
    );
  });

  it('should infer dark color scheme from prefers-color-scheme when no theme is set', () => {
    globalThis.matchMedia = vi.fn().mockImplementation(() => ({
      matches: true,
      media: '(prefers-color-scheme: dark)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    const playerHost = setupAndTrigger();

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?color_scheme=dark'
    );
  });

  it('should infer dark color scheme from body data-bs-theme when html has no theme', () => {
    document.body.setAttribute('data-bs-theme', 'dark');
    const playerHost = setupAndTrigger();

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?color_scheme=dark'
    );
  });

  it('should infer dark color scheme from html data-theme fallback', () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    const playerHost = setupAndTrigger();

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/?color_scheme=dark'
    );
  });

  it('should prefer html data-bs-theme over body theme attributes', () => {
    document.documentElement.setAttribute('data-bs-theme', 'light');
    document.body.setAttribute('data-bs-theme', 'dark');
    globalThis.matchMedia = vi.fn().mockImplementation(() => ({
      matches: true,
      media: '(prefers-color-scheme: dark)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    const playerHost = setupAndTrigger();

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/'
    );
  });

  it('should keep explicit light theme even if prefers-color-scheme is dark', () => {
    document.documentElement.setAttribute('data-bs-theme', 'light');
    globalThis.matchMedia = vi.fn().mockImplementation(() => ({
      matches: true,
      media: '(prefers-color-scheme: dark)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    const playerHost = setupAndTrigger();

    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/'
    );
  });

  it('should include explicit-light background reset styles to override dark media query', () => {
    const element = document.createElement('podlove-player');
    document.body.appendChild(element);

    const style = document.getElementById('podlove-player-styles');
    expect(style).not.toBeNull();
    expect(style?.textContent).toContain('html[data-bs-theme="light"] podlove-player .podlove-player-container');
    expect(style?.textContent).toContain('background-color: #ffffff');
  });

  it('should not initialize the player when not in view', () => {
    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    document.body.appendChild(element);

    // Access the observer
    const observerInstance = element.observer;

    // Simulate the IntersectionObserver callback with isIntersecting false
    const entries = [{ isIntersecting: false, target: element }];
    observerInstance.callback(entries, observerInstance);

    // Check that podlovePlayer was not called
    expect(global.podlovePlayer).not.toHaveBeenCalled();
  });

  it('should initialize the player only once', () => {
    const unobserveSpy = vi.spyOn(IntersectionObserver.prototype, 'unobserve');

    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    document.body.appendChild(element);

    // Access the observer instance
    const observerInstance = element.observer as IntersectionObserverMock;

    // Simulate the IntersectionObserver callback multiple times
    const entries = [{ isIntersecting: true, target: element } as IntersectionObserverEntry];

    // First trigger
    observerInstance.trigger(entries);

    // Check that podlovePlayer was called once
    expect(globalThis.podlovePlayer).toHaveBeenCalledTimes(1);

    // Second trigger (should not call podlovePlayer again)
    observerInstance.trigger(entries);

    // Check that podlovePlayer was still called only once
    expect(globalThis.podlovePlayer).toHaveBeenCalledTimes(1);

    // Check that unobserve was called
    expect(unobserveSpy).toHaveBeenCalledWith(element);

    unobserveSpy.mockRestore();
  });

  it('should initialize the player after click-to-load', () => {
    const observeSpy = vi.spyOn(IntersectionObserver.prototype, 'observe');

    const element = document.createElement('podlove-player');
    element.setAttribute('id', 'audio_63');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    element.setAttribute('data-load-mode', 'click');
    document.body.appendChild(element);

    expect(observeSpy).not.toHaveBeenCalled();

    const button = element.querySelector('.podlove-player-button') as HTMLButtonElement;
    button.click();

    const playerHost = element.querySelector('.podlove-player-host') as HTMLDivElement | null;
    expect(playerHost).not.toBeNull();
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      playerHost,
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/'
    );

    observeSpy.mockRestore();
  });

  it('should unobserve the element when it is removed', () => {
    const unobserveSpy = vi.spyOn(IntersectionObserver.prototype, 'unobserve');

    const element = document.createElement('podlove-player');
    document.body.appendChild(element);
    document.body.removeChild(element);

    expect(unobserveSpy).toHaveBeenCalledWith(element);
    unobserveSpy.mockRestore();
  });

  it('should show an error message when the embed script fails to load', async () => {
    const originalPodlovePlayer = global.podlovePlayer;
    global.podlovePlayer = undefined;

    const appendSpy = vi.spyOn(document.head, 'appendChild');
    const element = document.createElement('podlove-player');
    element.setAttribute('data-url', '/api/audios/podlove/63/post/75/');
    document.body.appendChild(element);

    const observerInstance = element.observer as IntersectionObserverMock;
    observerInstance.trigger([
      { isIntersecting: true, target: element } as IntersectionObserverEntry,
    ]);

    const script = document.querySelector('script[data-podlove-embed]') as HTMLScriptElement | null;
    expect(script).not.toBeNull();
    script?.dispatchEvent(new Event('error'));

    await new Promise((resolve) => setTimeout(resolve, 0));

    const errorMessage = element.querySelector('.podlove-player-error') as HTMLElement | null;
    expect(errorMessage).not.toBeNull();
    expect(errorMessage?.hidden).toBe(false);
    const container = element.querySelector('.podlove-player-container') as HTMLDivElement | null;
    expect(container?.style.minHeight).toBe('');
    expect(element.style.minHeight).toBe('');

    appendSpy.mockRestore();
    global.podlovePlayer = originalPodlovePlayer;
  });
});
