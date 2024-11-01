// podlove-player.ts
class PodlovePlayerElement extends HTMLElement {
  constructor() {
    super();
    this.observer = null;
    this.shadow = this.attachShadow({ mode: 'open' });
  }

  connectedCallback() {
    this.renderPlaceholder();

    if (document.readyState === 'complete') {
      // The page is already fully loaded
      this.observeElement();
    } else {
      // Wait for the 'load' event before initializing
      window.addEventListener('load', () => {
        this.observeElement();
      }, { once: true });
    }
  }

  disconnectedCallback() {
    if (this.observer) {
      this.observer.disconnect();
    }
  }

  renderPlaceholder() {
    // Reserve space to prevent layout shifts
    const container = document.createElement('div');
    container.classList.add('podlove-player-container');

    // Apply styles
    const style = document.createElement('style');
    style.textContent = `
      .podlove-player-container {
        width: 100%;
        max-width: 936px;
        height: 300px;
        margin: 0 auto;
      }
      @media (max-width: 768px) {
        .podlove-player-container {
          max-width: 366px;
          height: 500px;
        }
      }
      .podlove-player-container iframe {
        width: 100%;
        height: 100%;
        border: none;
      }
    `;

    this.shadow.appendChild(style);
    this.shadow.appendChild(container);
  }

  observeElement() {
    this.observer = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          this.initializePlayer();
          observer.unobserve(this);
        }
      });
    });
    this.observer.observe(this);
  }

  initializePlayer() {
    const container = this.shadow.querySelector('.podlove-player-container');
    const audioId = this.getAttribute('id') || `podlove-player-${Date.now()}`;
    const url = this.getAttribute('data-url');
    const configUrl = this.getAttribute('data-config') || '/api/audios/player_config/';
    const podloveTemplate = this.getAttribute('data-template');
    let embedUrl = this.getAttribute('data-embed') || 'https://cdn.podlove.org/web-player/5.x/embed.js';

    // If host ist localhost use local embed url
    const { protocol, hostname, port } = window.location;


    console.log("data template: ", podloveTemplate);
    const playerDiv = document.createElement('div');
    playerDiv.id = audioId;

    // set the template attribute if it is set (needed for pp theme)
    if (podloveTemplate !== null) {
        playerDiv.setAttribute('data-template', podloveTemplate);
    }
    container.appendChild(playerDiv);

    if (typeof podlovePlayer === 'function') {
      podlovePlayer(playerDiv, url, configUrl);
    } else {
      // If in dev mode on localhost and embedUrl starts with a slash, use the local embedUrl
      // otherwise the vite url 5173 will be used -> which will not work
      if (hostname === 'localhost' && embedUrl.startsWith("/")) {
        embedUrl = `http://localhost:${port}${embedUrl}`;
      }
      // Dynamically load the Podlove player script
      import(embedUrl).then(() => {
        podlovePlayer(playerDiv, url, configUrl);
      });
    }
  }
}

console.log("Registering podlove-player!");
customElements.define('podlove-player', PodlovePlayerElement);
