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
    global.podlovePlayer.mockReset();
    globalThis.requestIdleCallback = vi.fn((callback: IdleRequestCallback) => {
      callback({ didTimeout: false, timeRemaining: () => 50 });
      return 1;
    });
    globalThis.cancelIdleCallback = vi.fn();
  });

  it('should define the custom element', () => {
    expect(customElements.get('podlove-player')).toBeDefined();
  });

  it('should render the placeholder container', () => {
    const element = document.createElement('podlove-player');
    document.body.appendChild(element);

    const container = element.shadowRoot.querySelector('.podlove-player-container');
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
    expect(global.podlovePlayer).toHaveBeenCalledWith(
      element.shadowRoot.querySelector(`#${element.getAttribute('id')}`),
      '/api/audios/podlove/63/post/75/',
      '/api/audios/player_config/'
    );
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

    const button = element.shadowRoot.querySelector('.podlove-player-button') as HTMLButtonElement;
    button.click();

    expect(global.podlovePlayer).toHaveBeenCalledWith(
      element.shadowRoot.querySelector(`#${element.getAttribute('id')}`),
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

    const errorMessage = element.shadowRoot?.querySelector('.podlove-player-error') as HTMLElement | null;
    expect(errorMessage).not.toBeNull();
    expect(errorMessage?.hidden).toBe(false);

    appendSpy.mockRestore();
    global.podlovePlayer = originalPodlovePlayer;
  });
});
