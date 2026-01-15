var E=Object.defineProperty;var g=(r,o,e)=>o in r?E(r,o,{enumerable:!0,configurable:!0,writable:!0,value:e}):r[o]=e;var l=(r,o,e)=>g(r,typeof o!="symbol"?o+"":o,e);let s=null,c=null,u=null;const L=200,T="200px 0px",w="data-load-mode",A="click",C="Load player",_="Loading player...",D="Try again",I="Unable to load the audio player. Please try again.",f="data-podlove-embed",v="data-podlove-embed-loaded",h="data-podlove-embed-failed";function x(){return document.readyState==="complete"?Promise.resolve():(c||(c=new Promise(r=>{window.addEventListener("load",()=>r(),{once:!0})})),c)}function P(){return u||(u=new IntersectionObserver((r,o)=>{r.forEach(e=>{if(!e.isIntersecting)return;const t=e.target;t instanceof m&&t.scheduleInitialize(),o.unobserve(t)})},{rootMargin:T})),u}function B(r){return typeof podlovePlayer=="function"?Promise.resolve():s||(s=new Promise((o,e)=>{const t=document.querySelector(`script[${f}]`);if(t){if(t.getAttribute(v)==="true"&&typeof podlovePlayer=="function"){o();return}if(t.getAttribute(h)==="true")t.remove();else{t.addEventListener("load",()=>o(),{once:!0}),t.addEventListener("error",()=>{t.setAttribute(h,"true"),t.remove(),s=null,e(new Error("Failed to load Podlove embed script"))},{once:!0});return}}const i=document.createElement("script");i.src=r,i.async=!0,i.setAttribute(f,"true"),i.addEventListener("load",()=>{i.setAttribute(v,"true"),o()},{once:!0}),i.addEventListener("error",()=>{i.setAttribute(h,"true"),i.remove(),s=null,e(new Error("Failed to load Podlove embed script"))},{once:!0}),document.head.appendChild(i)}),s)}function k(r){return typeof window.requestIdleCallback=="function"?window.requestIdleCallback(()=>r(),{timeout:L}):window.setTimeout(()=>r(),0)}function O(r){if(typeof window.cancelIdleCallback=="function"){window.cancelIdleCallback(r);return}window.clearTimeout(r)}class m extends HTMLElement{constructor(){super();l(this,"observer");l(this,"shadow");l(this,"isInitialized");l(this,"isScheduled");l(this,"idleHandle");l(this,"loadButton");l(this,"clickHandler");l(this,"errorMessage");l(this,"playerDiv");this.observer=null,this.isInitialized=!1,this.isScheduled=!1,this.idleHandle=null,this.loadButton=null,this.clickHandler=null,this.errorMessage=null,this.playerDiv=null,this.shadow=this.attachShadow({mode:"open"})}connectedCallback(){const e=this.shouldClickToLoad();if(this.renderPlaceholder(e),e){this.setupClickToLoad();return}if(document.readyState==="complete"){this.observeElement();return}x().then(()=>this.observeElement())}disconnectedCallback(){this.observer&&this.observer.unobserve(this),this.loadButton&&this.clickHandler&&this.loadButton.removeEventListener("click",this.clickHandler),this.idleHandle!==null&&(O(this.idleHandle),this.idleHandle=null)}shouldClickToLoad(){return this.getAttribute(w)===A}renderPlaceholder(e){const t=document.createElement("div");t.classList.add("podlove-player-container"),e&&t.classList.add("podlove-player-click-to-load");const i=document.createElement("style");i.textContent=`
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
    `,this.shadow.appendChild(i),this.shadow.appendChild(t);const a=document.createElement("p");if(a.classList.add("podlove-player-error"),a.hidden=!0,a.setAttribute("role","alert"),a.textContent=I,t.appendChild(a),this.errorMessage=a,e){const n=document.createElement("button");n.type="button",n.textContent=C,n.classList.add("podlove-player-button"),n.setAttribute("aria-label","Load audio player"),t.appendChild(n),this.loadButton=n}}observeElement(){this.observer=P(),this.observer.observe(this)}setupClickToLoad(){this.loadButton&&(this.clickHandler=()=>{this.clearError(),this.loadButton&&(this.loadButton.disabled=!0,this.loadButton.textContent=_),this.scheduleInitialize()},this.loadButton.addEventListener("click",this.clickHandler))}scheduleInitialize(){this.isInitialized||this.isScheduled||(this.isScheduled=!0,this.idleHandle=k(()=>{this.idleHandle=null,this.isScheduled=!1,this.initializePlayer()}))}initializePlayer(){if(this.isInitialized)return;const e=this.shadow.querySelector(".podlove-player-container");if(!e)return;const t=this.getAttribute("data-url");if(!t)return;let i=this.getAttribute("id");i||(i=`podlove-player-${Date.now()}`,this.setAttribute("id",i)),this.isInitialized=!0,this.clearError();const a=this.getAttribute("data-config")||"/api/audios/player_config/",n=this.getAttribute("data-template");let d=this.getAttribute("data-embed")||"https://cdn.podlove.org/web-player/5.x/embed.js";const{hostname:b,port:y}=window.location,p=this.getOrCreatePlayerDiv(e,i,n);if(typeof podlovePlayer=="function"){podlovePlayer(p,t,a),this.finalizeLoad(e);return}b==="localhost"&&d.startsWith("/")&&(d=`http://localhost:${y}${d}`),B(d).then(()=>{if(typeof podlovePlayer=="function"){podlovePlayer(p,t,a),this.finalizeLoad(e);return}this.handleLoadError()}).catch(()=>{this.handleLoadError()})}getOrCreatePlayerDiv(e,t,i){return this.playerDiv||(this.playerDiv=document.createElement("div"),this.playerDiv.classList.add("podlove-player-host")),e.contains(this.playerDiv)||e.appendChild(this.playerDiv),this.playerDiv.id=t,i!==null?this.playerDiv.setAttribute("data-template",i):this.playerDiv.removeAttribute("data-template"),this.playerDiv}finalizeLoad(e){this.loadButton&&(this.loadButton.remove(),this.loadButton=null),e.classList.remove("podlove-player-click-to-load"),this.clearError()}clearError(){this.errorMessage&&(this.errorMessage.hidden=!0)}handleLoadError(){this.isInitialized=!1,this.errorMessage&&(this.errorMessage.hidden=!1),this.loadButton&&(this.loadButton.disabled=!1,this.loadButton.textContent=D)}}customElements.define("podlove-player",m);
