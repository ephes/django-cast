import{t as e}from"./defineProperty-BbfpZ9Tg.js";var t=null,n=null,r=null,i=0,a=200,o=`200px 0px`,s=`data-load-mode`,c=`click`,l=`Load player`,u=`Loading player...`,d=`Try again`,f=`Unable to load the audio player. Please try again.`,p=`Unable to load the audio player because no Podlove embed script is configured.`,m=`data-podlove-embed`,h=`data-podlove-embed-loaded`,g=`data-podlove-embed-failed`,_=`podlove-player-styles`,v=`color_scheme`,y=`#1e293b`,b=`#ffffff`;function x(){return document.readyState===`complete`?Promise.resolve():(n||(n=new Promise(e=>{window.addEventListener(`load`,()=>e(),{once:!0})})),n)}function S(){return r||(r=new IntersectionObserver((e,t)=>{e.forEach(e=>{if(!e.isIntersecting)return;let n=e.target;n instanceof k&&n.scheduleInitialize(),t.unobserve(n)})},{rootMargin:o})),r}function C(e){return typeof podlovePlayer==`function`?Promise.resolve():t||(t=new Promise((n,r)=>{let i=document.querySelector(`script[${m}]`);if(i){if(i.getAttribute(h)===`true`&&typeof podlovePlayer==`function`){n();return}if(i.getAttribute(g)===`true`)i.remove();else{i.addEventListener(`load`,()=>n(),{once:!0}),i.addEventListener(`error`,()=>{i.setAttribute(g,`true`),i.remove(),t=null,r(Error(`Failed to load Podlove embed script`))},{once:!0});return}}let a=document.createElement(`script`);a.src=e,a.async=!0,a.setAttribute(m,`true`),a.addEventListener(`load`,()=>{a.setAttribute(h,`true`),n()},{once:!0}),a.addEventListener(`error`,()=>{a.setAttribute(g,`true`),a.remove(),t=null,r(Error(`Failed to load Podlove embed script`))},{once:!0}),document.head.appendChild(a)}),t)}function w(e){return typeof window.requestIdleCallback==`function`?window.requestIdleCallback(()=>e(),{timeout:a}):window.setTimeout(()=>e(),0)}function T(e){if(typeof window.cancelIdleCallback==`function`){window.cancelIdleCallback(e);return}window.clearTimeout(e)}function E(){var e,t;let n=document.documentElement.getAttribute(`data-bs-theme`)||document.documentElement.getAttribute(`data-theme`)||((e=document.body)==null?void 0:e.getAttribute(`data-bs-theme`))||((t=document.body)==null?void 0:t.getAttribute(`data-theme`));return n===`light`||n===`dark`?n:null}function D(){let e=E();return e?e===`dark`:typeof window.matchMedia==`function`?window.matchMedia(`(prefers-color-scheme: dark)`).matches:!1}function O(e){if(!D())return e;let t=e.indexOf(`#`),n=t===-1?e:e.slice(0,t),r=t===-1?``:e.slice(t),i=n.indexOf(`?`),a=i===-1?n:n.slice(0,i),o=i===-1?``:n.slice(i+1),s=new URLSearchParams(o);if(s.has(v))return e;s.set(v,`dark`);let c=s.toString();return c?`${a}?${c}${r}`:`${a}${r}`}var k=class extends HTMLElement{constructor(){super(),e(this,`observer`,void 0),e(this,`isInitialized`,void 0),e(this,`isScheduled`,void 0),e(this,`idleHandle`,void 0),e(this,`loadButton`,void 0),e(this,`clickHandler`,void 0),e(this,`errorMessage`,void 0),e(this,`playerDiv`,void 0),this.observer=null,this.isInitialized=!1,this.isScheduled=!1,this.idleHandle=null,this.loadButton=null,this.clickHandler=null,this.errorMessage=null,this.playerDiv=null}connectedCallback(){let e=this.shouldClickToLoad();if(this.renderPlaceholder(e),e){this.setupClickToLoad();return}if(document.readyState===`complete`){this.observeElement();return}x().then(()=>this.observeElement())}disconnectedCallback(){this.observer&&this.observer.unobserve(this),this.loadButton&&this.clickHandler&&this.loadButton.removeEventListener(`click`,this.clickHandler),this.idleHandle!==null&&(T(this.idleHandle),this.idleHandle=null)}shouldClickToLoad(){return this.getAttribute(s)===c}renderPlaceholder(e){if(this.querySelector(`.podlove-player-container`))return;if(!document.getElementById(_)){let e=document.createElement(`style`);e.id=_,e.textContent=`
        podlove-player .podlove-player-container {
          width: 100%;
          max-width: 936px;
          min-height: 300px;
          margin: 0 auto;
          background-color: ${b};
        }
        @media (max-width: 768px) {
          podlove-player .podlove-player-container {
            max-width: 366px;
            min-height: 500px;
          }
        }
        podlove-player .podlove-player-click-to-load {
          display: flex;
          flex-direction: column;
          gap: 0.8rem;
          align-items: center;
          justify-content: center;
          background: #f6f6f6;
          border: 1px solid #e3e3e3;
          border-radius: 8px;
        }
        podlove-player .podlove-player-button {
          appearance: none;
          border: 1px solid #1a1a1a;
          background: #1a1a1a;
          color: #ffffff;
          border-radius: 999px;
          font-size: 0.95rem;
          padding: 0.6rem 1.4rem;
          cursor: pointer;
        }
        podlove-player .podlove-player-button:focus-visible {
          outline: 3px solid #6aa5ff;
          outline-offset: 3px;
        }
        podlove-player .podlove-player-button:disabled {
          opacity: 0.7;
          cursor: progress;
        }
        podlove-player .podlove-player-error {
          margin: 1.2rem;
          color: #b42318;
          font-size: 0.95rem;
          text-align: center;
        }
        podlove-player .podlove-player-container iframe {
          width: 100%;
          height: 100%;
          border: none;
          background-color: ${b};
        }
        @media (prefers-color-scheme: dark) {
          podlove-player .podlove-player-container {
            background-color: ${y};
          }
          podlove-player .podlove-player-container iframe {
            background-color: ${y};
            color-scheme: dark;
          }
        }
        html[data-bs-theme="dark"] podlove-player .podlove-player-container,
        html[data-theme="dark"] podlove-player .podlove-player-container,
        body[data-bs-theme="dark"] podlove-player .podlove-player-container,
        body[data-theme="dark"] podlove-player .podlove-player-container {
          background-color: ${y};
        }
        html[data-bs-theme="dark"] podlove-player .podlove-player-container iframe,
        html[data-theme="dark"] podlove-player .podlove-player-container iframe,
        body[data-bs-theme="dark"] podlove-player .podlove-player-container iframe,
        body[data-theme="dark"] podlove-player .podlove-player-container iframe {
          background-color: ${y};
          color-scheme: dark;
        }
        html[data-bs-theme="light"] podlove-player .podlove-player-container iframe,
        html[data-theme="light"] podlove-player .podlove-player-container iframe,
        body[data-bs-theme="light"] podlove-player .podlove-player-container iframe,
        body[data-theme="light"] podlove-player .podlove-player-container iframe {
          background-color: ${b};
          color-scheme: light;
        }
        html[data-bs-theme="light"] podlove-player .podlove-player-container,
        html[data-theme="light"] podlove-player .podlove-player-container,
        body[data-bs-theme="light"] podlove-player .podlove-player-container,
        body[data-theme="light"] podlove-player .podlove-player-container {
          background-color: ${b};
        }
      `,document.head.appendChild(e)}let t=document.createElement(`div`);t.classList.add(`podlove-player-container`),e&&t.classList.add(`podlove-player-click-to-load`),this.appendChild(t);let n=document.createElement(`p`);if(n.classList.add(`podlove-player-error`),n.hidden=!0,n.setAttribute(`role`,`alert`),n.textContent=f,t.appendChild(n),this.errorMessage=n,e){let e=document.createElement(`button`);e.type=`button`,e.textContent=l,e.classList.add(`podlove-player-button`),e.setAttribute(`aria-label`,`Load audio player`),t.appendChild(e),this.loadButton=e}}observeElement(){this.observer=S(),this.observer.observe(this)}setupClickToLoad(){this.loadButton&&(this.clickHandler=()=>{this.clearError(),this.loadButton&&(this.loadButton.disabled=!0,this.loadButton.textContent=u),this.scheduleInitialize()},this.loadButton.addEventListener(`click`,this.clickHandler))}scheduleInitialize(){this.isInitialized||this.isScheduled||(this.isScheduled=!0,this.idleHandle=w(()=>{this.idleHandle=null,this.isScheduled=!1,this.initializePlayer()}))}initializePlayer(){if(this.isInitialized)return;let e=this.querySelector(`.podlove-player-container`);if(!e)return;let t=this.getAttribute(`data-url`);if(!t)return;let n=this.getAttribute(`id`);n||(n=`podlove-player-${Date.now()}`,this.setAttribute(`id`,n)),this.dataset.playerInstanceId||(i+=1,this.dataset.playerInstanceId=String(i));let r=`${n}-player-${this.dataset.playerInstanceId}`;this.isInitialized=!0,this.clearError();let a=O(this.getAttribute(`data-config`)||`/api/audios/player_config/`),o=this.getAttribute(`data-template`),s=this.getAttribute(`data-embed`),{hostname:c,port:l}=window.location,u=this.getOrCreatePlayerDiv(e,r,o);if(typeof podlovePlayer==`function`){podlovePlayer(u,t,a),this.finalizeLoad(e);return}if(!s){this.handleLoadError(p);return}c===`localhost`&&s.startsWith(`/`)&&(s=`http://localhost:${l}${s}`),C(s).then(()=>{if(typeof podlovePlayer==`function`){podlovePlayer(u,t,a),this.finalizeLoad(e);return}this.handleLoadError()}).catch(()=>{this.handleLoadError()})}getOrCreatePlayerDiv(e,t,n){return this.playerDiv||(this.playerDiv=document.createElement(`div`),this.playerDiv.classList.add(`podlove-player-host`)),e.contains(this.playerDiv)||e.appendChild(this.playerDiv),this.playerDiv.id=t,n===null?this.playerDiv.removeAttribute(`data-template`):this.playerDiv.setAttribute(`data-template`,n),this.playerDiv}finalizeLoad(e){e instanceof HTMLElement&&(e.style.minHeight=`auto`),this.style.minHeight=`auto`,this.loadButton&&(this.loadButton.remove(),this.loadButton=null),e.classList.remove(`podlove-player-click-to-load`),this.clearError()}clearError(){this.errorMessage&&(this.errorMessage.hidden=!0)}handleLoadError(e=f){this.isInitialized=!1,this.errorMessage&&(this.errorMessage.textContent=e,this.errorMessage.hidden=!1),this.loadButton&&(this.loadButton.disabled=!1,this.loadButton.textContent=d)}};customElements.define(`podlove-player`,k);