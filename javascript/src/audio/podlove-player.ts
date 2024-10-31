// podlove-player.ts
class PodlovePlayerElement extends HTMLElement {
  constructor() {
    super();
    this.observer = null;
    this.shadow = this.attachShadow({ mode: 'open' });
  }

  connectedCallback() {
    this.renderPlaceholder();
    this.observeElement();
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
    let embedUrl = this.getAttribute('data-embed') || 'https://cdn.podlove.org/web-player/5.x/embed.js';

    // If host ist localhost use local embed url
    const { protocol, hostname, port } = window.location;
    console.log("protocol, hostname, port: ", protocol, hostname, port);

    const playerDiv = document.createElement('div');
    playerDiv.id = audioId;
    container.appendChild(playerDiv);

    if (typeof podlovePlayer === 'function') {
      // Initialize existing Podlove player
      console.log("embed url: ", embedUrl);
      console.log("starting podlove player with: ", playerDiv, url, configUrl);
      podlovePlayer(playerDiv, url, configUrl);
    } else {
      // If in dev mode on localhost and embedUrl starts with a slash, use the local embedUrl
      // otherwise the vite url 5173 will be used -> which will not work
      if (hostname === 'localhost' && embedUrl.startsWith("/")) {
        embedUrl = `http://localhost:${port}${embedUrl}`;
      }
      console.log("importing embed via url: ", embedUrl);
      // Dynamically load the Podlove player script
      import(embedUrl).then(() => {
        // Create a div with a unique ID inside the shadow DOM
        const playerDiv = document.createElement('div');

        playerDiv.id = audioId;
        container.appendChild(playerDiv);

        // Initialize the Podlove player
        podlovePlayer(playerDiv, url, configUrl);
      });
    }
  }
}

console.log("Registering podlove-player!");
customElements.define('podlove-player', PodlovePlayerElement);
